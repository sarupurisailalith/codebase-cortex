"""NotionBackend — reads/writes documentation via Notion MCP (Streamable HTTP)."""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

from codebase_cortex.config import Settings
from codebase_cortex.notion.page_cache import PageCache


logger = logging.getLogger("cortex")


# ---------------------------------------------------------------------------
# Notion text helpers (extracted from agents/doc_writer.py)
# ---------------------------------------------------------------------------


def _unescape_notion_text(text: str) -> str:
    """Convert literal escape sequences from Notion MCP responses to real characters.

    The Notion MCP server returns page content with literal \\n and \\t
    (two-character sequences) instead of real newline/tab characters.
    """
    result: list[str] = []
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

    The notion-fetch tool returns XML-like wrapper with metadata.
    This extracts only the content between <content> tags,
    or falls back to stripping all XML-like tags.
    """
    raw_text = _unescape_notion_text(raw_text)

    content_match = re.search(
        r"<content>\s*(.*?)\s*</content>",
        raw_text,
        re.DOTALL,
    )
    if content_match:
        return content_match.group(1).strip()

    # Fallback: strip the "Here is the result..." header and XML tags
    text = re.sub(r'^Here is the result of "view".*?\n', "", raw_text)
    text = re.sub(r"</?(?:page|ancestor-path|parent-page|properties|content)[^>]*>", "", text)
    text = re.sub(r'^\s*\{.*?"title".*?\}\s*$', "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


class NotionBackend:
    """Backend that reads/writes documentation via the Notion MCP server.

    Consolidates Notion interaction logic previously scattered across
    DocWriterAgent, TaskCreatorAgent, SprintReporterAgent, and bootstrap.py.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.cache = PageCache(cache_path=settings.page_cache_path)
        self._parent_title = settings.repo_path.name

    # ------------------------------------------------------------------
    # DocBackend protocol methods
    # ------------------------------------------------------------------

    async def fetch_page_list(self) -> list[dict]:
        """Return list of pages from the Notion page cache.

        Each dict has: ref (page_id), title, sections (empty for Notion —
        section parsing happens in fetch_section).
        """
        doc_pages = self.cache.find_all_doc_pages(parent_title=self._parent_title)
        return [
            {
                "ref": p.page_id,
                "title": p.title,
                "sections": [],  # Notion doesn't pre-index sections
            }
            for p in doc_pages
        ]

    async def fetch_section(
        self,
        page_ref: str,
        heading: str,
        line_range: tuple[int, int] | None = None,
    ) -> str:
        """Fetch a page from Notion and extract a section by heading.

        Args:
            page_ref: Notion page ID.
            heading: The section heading to extract.
            line_range: Ignored for Notion (no line-based access).
        """
        from codebase_cortex.utils.section_parser import parse_sections, normalize_heading

        content = await self._fetch_page_content(page_ref)
        if not content:
            return ""

        sections = parse_sections(content)
        target = normalize_heading(heading)
        for section in sections:
            if section.heading and normalize_heading(section.heading) == target:
                return section.content
        return ""

    async def write_page(
        self,
        page_ref: str,
        title: str,
        content: str,
        action: str,
    ) -> str:
        """Write a full page to Notion. Returns page ID."""
        from codebase_cortex.mcp_client import notion_mcp_session, rate_limiter
        from codebase_cortex.notion.bootstrap import extract_page_id

        async with notion_mcp_session(self.settings) as session:
            await rate_limiter.acquire()

            if page_ref and action == "update":
                # Update existing page
                await session.call_tool(
                    "notion-update-page",
                    arguments={
                        "page_id": page_ref,
                        "command": "replace_content",
                        "new_str": content,
                    },
                )
                content_hash = hashlib.md5(content.encode()).hexdigest()[:8]
                self.cache.upsert(page_ref, title, content_hash=content_hash)
                logger.info(f"Updated: {title}")
                return page_ref
            else:
                # Create new page under parent
                parent_page = self.cache.find_by_title(self._parent_title)
                parent_id = parent_page.page_id if parent_page else None

                create_args: dict[str, Any] = {
                    "pages": [
                        {
                            "properties": {"title": title},
                            "content": content,
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
                    content_hash = hashlib.md5(content.encode()).hexdigest()[:8]
                    self.cache.upsert(new_page_id, title, content_hash=content_hash)
                logger.info(f"Created: {title}")
                return new_page_id or ""

    async def write_section(
        self,
        page_ref: str,
        heading: str,
        content: str,
    ) -> None:
        """Write a single section: fetch full page, merge, write back."""
        from codebase_cortex.utils.section_parser import merge_sections, parse_sections

        existing_content = await self._fetch_page_content(page_ref)
        if not existing_content:
            # Page doesn't exist or is empty — write full content
            await self.write_page(page_ref, heading.lstrip("# "), content, "update")
            return

        existing_sections = parse_sections(existing_content)
        merged = merge_sections(
            existing_sections,
            [{"heading": heading, "content": content, "action": "update"}],
        )

        cached = self.cache.get(page_ref)
        title = cached.title if cached else heading.lstrip("# ")
        await self.write_page(page_ref, title, merged, "update")

    async def create_task(
        self,
        task: dict,
        parent_ref: str | None = None,
    ) -> None:
        """Create a task item as a child page under the Task Board in Notion."""
        from codebase_cortex.mcp_client import notion_mcp_session, rate_limiter
        from codebase_cortex.notion.bootstrap import extract_page_id

        priority = task.get("priority", "medium")
        title = task.get("title", "Untitled task")
        description = task.get("description", "")
        priority_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(priority, "⚪")

        display_title = f"{priority_icon} {title}"
        content = (
            f"## {title}\n\n"
            f"**Priority:** {priority}\n\n"
            f"{description}\n\n"
            "---\n*Auto-created by Codebase Cortex*"
        )

        # Find parent: Task Board, or explicit parent_ref, or repo root
        task_board = self.cache.find_by_title("Task Board")
        parent_page = self.cache.find_by_title(self._parent_title)
        parent_id = parent_ref or (task_board and task_board.page_id) or (parent_page and parent_page.page_id)

        async with notion_mcp_session(self.settings) as session:
            await rate_limiter.acquire()

            create_args: dict[str, Any] = {
                "pages": [
                    {
                        "properties": {"title": display_title},
                        "content": content,
                    }
                ],
            }
            if parent_id:
                create_args["parent"] = {"page_id": parent_id}

            result = await session.call_tool(
                "notion-create-pages",
                arguments=create_args,
            )
            page_id = extract_page_id(result)
            if page_id:
                self.cache.upsert(page_id, title)
            logger.info(f"Created task: {display_title}")

    async def append_to_log(self, page_ref: str, content: str) -> None:
        """Append content to the Sprint Log page in Notion.

        Replaces the Sprint Log page content (Notion doesn't support
        true append via MCP — we fetch, prepend new entry, and replace).
        """
        from codebase_cortex.mcp_client import notion_mcp_session, rate_limiter
        from codebase_cortex.notion.bootstrap import extract_page_id
        from datetime import datetime

        sprint_page = self.cache.find_by_title("Sprint Log")
        parent_page = self.cache.find_by_title(self._parent_title)

        week_label = datetime.now().strftime("%B %d, %Y")
        full_content = f"# Sprint Report — Week of {week_label}\n\n{content}"

        async with notion_mcp_session(self.settings) as session:
            await rate_limiter.acquire()

            if sprint_page:
                await session.call_tool(
                    "notion-update-page",
                    arguments={
                        "page_id": sprint_page.page_id,
                        "command": "replace_content",
                        "new_str": full_content,
                    },
                )
                logger.info(f"Updated Sprint Log for week of {week_label}")
            else:
                parent_id = parent_page.page_id if parent_page else None
                create_args: dict[str, Any] = {
                    "pages": [
                        {
                            "properties": {"title": f"📋 Sprint Report — {week_label}"},
                            "content": full_content,
                        }
                    ],
                }
                if parent_id:
                    create_args["parent"] = {"page_id": parent_id}

                result = await session.call_tool(
                    "notion-create-pages",
                    arguments=create_args,
                )
                page_id = extract_page_id(result)
                if page_id:
                    self.cache.upsert(page_id, "Sprint Log")
                logger.info(f"Created Sprint Report for week of {week_label}")

    async def search_pages(self, query: str) -> list[dict]:
        """Search Notion workspace by query string."""
        from codebase_cortex.mcp_client import notion_mcp_session, rate_limiter

        results: list[dict] = []

        try:
            async with notion_mcp_session(self.settings) as session:
                await rate_limiter.acquire()
                result = await session.call_tool(
                    "notion-search",
                    arguments={"query": query},
                )
                if not result.isError and result.content:
                    text = result.content[0].text
                    # Extract page references from search results
                    uuid_pattern = r"[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}"
                    from codebase_cortex.notion.bootstrap import normalize_page_id
                    for match in re.finditer(uuid_pattern, text, re.IGNORECASE):
                        page_id = normalize_page_id(match.group(0))
                        cached = self.cache.get(page_id)
                        if cached:
                            results.append({
                                "ref": page_id,
                                "title": cached.title,
                            })
        except Exception as e:
            logger.warning(f"Notion search failed: {e}")

        return results

    # ------------------------------------------------------------------
    # Notion-specific helpers
    # ------------------------------------------------------------------

    async def fetch_existing_pages(self) -> dict[str, str]:
        """Fetch current content of all doc pages from Notion.

        Returns a {title: content} dict for use by agents.
        Also syncs page titles back to cache (detects renames).
        """
        from codebase_cortex.mcp_client import notion_mcp_session, rate_limiter

        existing: dict[str, str] = {}
        doc_pages = self.cache.find_all_doc_pages(parent_title=self._parent_title)
        pages_to_fetch = doc_pages[:10]

        if not pages_to_fetch:
            return existing

        try:
            async with notion_mcp_session(self.settings) as session:
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
                            title_match = re.search(
                                r'"title"\s*:\s*"([^"]+)"', raw
                            )
                            if title_match:
                                actual_title = title_match.group(1)
                                normalized_actual = self.cache._normalize_title(actual_title)
                                normalized_cached = self.cache._normalize_title(cached_page.title)
                                if normalized_actual != normalized_cached and normalized_actual:
                                    logger.info(
                                        f"Page renamed: '{cached_page.title}' → '{actual_title}'"
                                    )
                                    self.cache.upsert(
                                        cached_page.page_id, actual_title
                                    )
                    except Exception as e:
                        logger.warning(f"Could not fetch {cached_page.title}: {e}")
        except Exception as e:
            logger.warning(f"Could not fetch existing pages: {e}")

        return existing

    async def _fetch_page_content(self, page_id: str) -> str:
        """Fetch and clean a single page's content from Notion."""
        from codebase_cortex.mcp_client import notion_mcp_session, rate_limiter

        try:
            async with notion_mcp_session(self.settings) as session:
                await rate_limiter.acquire()
                result = await session.call_tool(
                    "notion-fetch",
                    arguments={"id": page_id},
                )
                if not result.isError and result.content:
                    return strip_notion_metadata(result.content[0].text)
        except Exception as e:
            logger.warning(f"Failed to fetch page {page_id}: {e}")
        return ""
