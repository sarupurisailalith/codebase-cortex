"""DocWriter agent — updates or creates Notion pages to reflect code changes."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

import re

from codebase_cortex.agents.base import BaseAgent
from codebase_cortex.config import Settings
from codebase_cortex.notion.bootstrap import extract_page_id
from codebase_cortex.notion.page_cache import PageCache
from codebase_cortex.state import CortexState, DocUpdate
from codebase_cortex.utils.json_parsing import parse_json_array
from codebase_cortex.utils.section_parser import merge_sections, parse_sections


def _unescape_notion_text(text: str) -> str:
    """Convert literal escape sequences from Notion MCP responses to real characters.

    The Notion MCP server returns page content with literal \\n and \\t
    (two-character sequences) instead of real newline/tab characters.
    This converts them back so markdown parsing works correctly.
    """
    # Replace literal \n and \t with real characters
    # Use a single pass to handle \n and \t without touching \\n (escaped backslash + n)
    result = []
    i = 0
    while i < len(text):
        if text[i] == '\\' and i + 1 < len(text):
            next_char = text[i + 1]
            if next_char == 'n':
                result.append('\n')
                i += 2
                continue
            elif next_char == 't':
                result.append('\t')
                i += 2
                continue
        result.append(text[i])
        i += 1
    return ''.join(result)


def strip_notion_metadata(raw_text: str) -> str:
    """Extract just the page content from a notion-fetch response.

    The notion-fetch tool returns XML-like wrapper with metadata:
        Here is the result of "view" for the Page ...
        <page url="...">
        <ancestor-path>...</ancestor-path>
        <properties>...</properties>
        <content>
        ... actual markdown content ...
        </content>
        </page>

    This function extracts only the content between <content> tags,
    or falls back to stripping all XML-like tags.
    """
    # Notion MCP returns literal \n instead of real newlines — unescape first
    raw_text = _unescape_notion_text(raw_text)

    # Try to extract content between <content> and </content>
    content_match = re.search(
        r"<content>\s*(.*?)\s*</content>",
        raw_text,
        re.DOTALL,
    )
    if content_match:
        return content_match.group(1).strip()

    # Fallback: strip the "Here is the result..." header and XML tags
    # Remove the leading metadata line
    text = re.sub(r'^Here is the result of "view".*?\n', "", raw_text)
    # Remove XML-like tags
    text = re.sub(r"</?(?:page|ancestor-path|parent-page|properties|content)[^>]*>", "", text)
    # Remove JSON property lines like {"title":"..."}
    text = re.sub(r'^\s*\{.*?"title".*?\}\s*$', "", text, flags=re.MULTILINE)
    # Clean up excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

SYSTEM_PROMPT = """You are a technical documentation writer. Given a code analysis
and related existing documentation, generate documentation updates for a Notion workspace.

Output a JSON array of page updates. Each element has:
- "title": Page title (must match an existing page title when updating)
- "action": "update" or "create"

For "update" actions (modifying an existing page):
- Include "section_updates": a JSON array of ONLY the sections that changed.
- Each section update has:
  - "heading": The exact markdown heading (e.g., "## API Endpoints", "### Authentication")
  - "content": The new content for that section (everything below the heading until the next heading)
  - "action": "update" to replace an existing section, or "create" to add a new section
- Do NOT include sections that haven't changed.
- Match headings exactly to existing page headings (case-insensitive matching is applied).

For "create" actions (new page):
- Include "content": Full markdown content for the new page.
- Do NOT include "section_updates".

Focus on:
- Architecture decisions and component relationships
- API contracts and interfaces
- How components interact
- Breaking changes and migration notes

Keep content concise and actionable. Use markdown headings, lists, and code blocks."""


class DocWriterAgent(BaseAgent):
    """Writes and updates documentation in Notion via MCP tools.

    Uses LLM to generate documentation content based on code analysis
    and related docs, then writes to Notion via MCP (or logs in dry_run mode).
    """

    async def run(self, state: CortexState) -> dict:
        analysis = state.get("analysis", "")
        if not analysis:
            return {"doc_updates": []}

        related_docs = state.get("related_docs", [])
        dry_run = state.get("dry_run", False)

        settings = Settings.from_env()
        cache = PageCache(cache_path=settings.page_cache_path)

        # Step 1: Fetch existing content from all Notion doc pages
        existing_pages = await self._fetch_existing_pages(settings, cache)

        # Build context from related code chunks (actual content, not just titles)
        related_context = ""
        if related_docs:
            related_context = "\n\n## Related Code\n"
            for doc in related_docs[:5]:
                related_context += f"\n### {doc['title']} (similarity: {doc['similarity']:.2f})\n"
                if doc.get("content"):
                    related_context += f"```\n{doc['content'][:1500]}\n```\n"

        # Build existing page content section for the LLM
        # Show section structure so the LLM knows which headings exist
        existing_content_section = ""
        if existing_pages:
            existing_content_section = "\n\n## Current Page Contents\n"
            for title, content in existing_pages.items():
                truncated = content[:3000] + ("..." if len(content) > 3000 else "")
                existing_content_section += f"\n### {title}\n```\n{truncated}\n```\n"

        # Build dynamic page list from cache
        doc_pages = cache.find_all_doc_pages(parent_title=settings.repo_path.name)
        page_list = "\n".join(f"- {p.title}" for p in doc_pages) if doc_pages else "- (no pages yet)"

        # Ask LLM to generate doc updates
        prompt = f"""Based on this code analysis, determine what documentation should be updated or created.

## Code Analysis
{analysis}
{related_context}
{existing_content_section}

## Available Pages in Notion
{page_list}

Generate documentation updates as a JSON array.
For "update" actions: include "title", "action", and "section_updates" (array of sections to change).
  Each section_update has "heading" (e.g. "## API Endpoints"), "content" (new content for that section), and "action" ("update" or "create").
  Only include sections that actually changed — unchanged sections will be preserved automatically.
For "create" actions: include "title", "action", and "content" (full markdown for new page).
Only include pages that genuinely need updating. Respond with ONLY the JSON array."""

        try:
            messages = [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ]
            raw = await self._invoke_llm(messages)

            updates_data = parse_json_array(raw)

        except Exception as e:
            return {
                "doc_updates": [],
                "errors": self._append_error(state, f"Doc generation failed: {e}"),
            }

        doc_updates: list[DocUpdate] = []

        # Build a normalized-title lookup for existing pages so that
        # "API Reference" matches "📡 API Reference" regardless of emoji.
        def _find_existing(title: str) -> str | None:
            """Return the existing_pages key that fuzzy-matches *title*, or None."""
            if title in existing_pages:
                return title
            norm = cache._normalize_title(title)
            for key in existing_pages:
                if cache._normalize_title(key) == norm:
                    return key
            return None

        for update in updates_data:
            title = update.get("title", "Untitled")
            action = update.get("action", "update")

            # Look up existing page ID from cache (handles emoji mismatch)
            cached = cache.find_by_title(title)
            page_id = cached.page_id if cached else None

            existing_key = _find_existing(title)

            if action == "update" and existing_key is not None:
                # Section-level merge for existing pages
                section_updates = update.get("section_updates")
                if section_updates:
                    # New format: merge only changed sections
                    existing_sections = parse_sections(existing_pages[existing_key])
                    content = merge_sections(existing_sections, section_updates)
                elif update.get("content"):
                    # Backward compatibility: LLM returned full content
                    content = update["content"]
                else:
                    continue
            else:
                # New page or page not in existing_pages
                content = update.get("content", "")
                if not content:
                    continue

            doc_updates.append(DocUpdate(
                page_id=page_id,
                title=title,
                content=content,
                action=action,
            ))

        # Write to Notion (unless dry_run)
        if not dry_run and doc_updates:
            await self._write_to_notion(doc_updates, cache, state)

        return {"doc_updates": doc_updates}

    async def _fetch_existing_pages(
        self, settings: Settings, cache: PageCache
    ) -> dict[str, str]:
        """Fetch current content of all doc pages from Notion.

        Also syncs page titles back to cache (detects renames).
        """
        from codebase_cortex.mcp_client import notion_mcp_session, rate_limiter
        from codebase_cortex.utils.logging import get_logger

        logger = get_logger()
        existing: dict[str, str] = {}

        # Fetch all doc pages (skip parent page)
        doc_pages = cache.find_all_doc_pages(parent_title=settings.repo_path.name)
        # Limit to 10 pages to avoid excessive API calls
        pages_to_fetch = doc_pages[:10]

        if not pages_to_fetch:
            return existing

        try:
            async with notion_mcp_session(settings) as session:
                for cached_page in pages_to_fetch:
                    await rate_limiter.acquire()
                    try:
                        result = await session.call_tool(
                            "notion-fetch",
                            arguments={"id": cached_page.page_id},
                        )
                        if not result.isError and result.content:
                            raw = result.content[0].text
                            content = strip_notion_metadata(raw)
                            existing[cached_page.title] = content

                            # Sync title back from Notion (detect renames)
                            # Extract actual title from the raw response
                            title_match = re.search(
                                r'"title"\s*:\s*"([^"]+)"', raw
                            )
                            if title_match:
                                actual_title = title_match.group(1)
                                normalized_actual = cache._normalize_title(actual_title)
                                normalized_cached = cache._normalize_title(cached_page.title)
                                if normalized_actual != normalized_cached and normalized_actual:
                                    logger.info(
                                        f"Page renamed: '{cached_page.title}' → '{actual_title}'"
                                    )
                                    cache.upsert(
                                        cached_page.page_id, actual_title
                                    )
                    except Exception as e:
                        logger.warning(f"Could not fetch {cached_page.title}: {e}")
        except Exception as e:
            logger.warning(f"Could not fetch existing pages: {e}")

        return existing

    async def _write_to_notion(
        self,
        updates: list[DocUpdate],
        cache: PageCache,
        state: CortexState,
    ) -> None:
        """Write documentation updates to Notion via MCP."""
        from codebase_cortex.mcp_client import notion_mcp_session, rate_limiter
        from codebase_cortex.config import Settings
        from codebase_cortex.utils.logging import get_logger

        logger = get_logger()
        settings = Settings.from_env()

        # Get parent page for new pages
        parent_title = settings.repo_path.name
        parent_page = cache.find_by_title(parent_title)
        parent_id = parent_page.page_id if parent_page else None

        try:
            async with notion_mcp_session(settings) as session:
                for update in updates:
                    await rate_limiter.acquire()

                    page_id = update["page_id"]
                    # Only update pages we already track in the cache.
                    # Never search the whole workspace — that risks
                    # overwriting unrelated user pages.

                    if page_id:
                        # Content already merged locally via section_parser
                        await session.call_tool(
                            "notion-update-page",
                            arguments={
                                "page_id": page_id,
                                "command": "replace_content",
                                "new_str": update["content"],
                            },
                        )
                        # Mark as written with a content hash so first-run detection works
                        import hashlib
                        content_hash = hashlib.md5(update["content"].encode()).hexdigest()[:8]
                        cache.upsert(page_id, update["title"], content_hash=content_hash)
                        logger.info(f"Updated: {update['title']}")
                    else:
                        # Create new page under parent
                        create_args: dict = {
                            "pages": [
                                {
                                    "properties": {"title": update["title"]},
                                    "content": update["content"],
                                }
                            ],
                        }
                        if parent_id:
                            create_args["parent"] = {"page_id": parent_id}

                        result = await session.call_tool(
                            "notion-create-pages",
                            arguments=create_args,
                        )
                        new_page_id = extract_page_id(result)
                        if new_page_id:
                            import hashlib
                            content_hash = hashlib.md5(update["content"].encode()).hexdigest()[:8]
                            cache.upsert(new_page_id, update["title"], content_hash=content_hash)
                        logger.info(f"Created: {update['title']}")

        except Exception as e:
            logger.error(f"Failed to write docs to Notion: {e}")
