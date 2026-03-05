"""DocWriter agent — updates or creates Notion pages to reflect code changes."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from codebase_cortex.agents.base import BaseAgent
from codebase_cortex.config import Settings
from codebase_cortex.notion.bootstrap import extract_page_id, search_page_by_title
from codebase_cortex.notion.page_cache import PageCache
from codebase_cortex.state import CortexState, DocUpdate
from codebase_cortex.utils.json_parsing import parse_json_array

SYSTEM_PROMPT = """You are a technical documentation writer. Given a code analysis
and related existing documentation, generate clear, well-structured documentation
updates for a Notion workspace.

Output a JSON array of documentation updates, each with:
- "title": Page title (match existing page titles when updating)
- "content": Markdown content for the page
- "action": "update" if modifying existing docs, "create" if new topic

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

        # Build context from related docs
        related_context = ""
        if related_docs:
            related_context = "\n\n## Related Existing Documentation\n"
            for doc in related_docs[:5]:
                related_context += f"- **{doc['title']}** (similarity: {doc['similarity']:.2f})\n"

        # Ask LLM to generate doc updates
        prompt = f"""Based on this code analysis, determine what documentation should be updated or created.

## Code Analysis
{analysis}
{related_context}

## Available Pages
- Architecture Overview
- API Reference
- Knowledge Map
- Sprint Log
- Task Board

Generate documentation updates as a JSON array. Each element should have "title", "content", and "action" fields.
Only include pages that genuinely need updating based on the changes. Respond with ONLY the JSON array."""

        try:
            messages = [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ]
            response = await self.llm.ainvoke(messages)
            raw = response.content

            updates_data = parse_json_array(raw)

        except Exception as e:
            return {
                "doc_updates": [],
                "errors": self._append_error(state, f"Doc generation failed: {e}"),
            }

        doc_updates: list[DocUpdate] = []
        settings = Settings.from_env()
        cache = PageCache(cache_path=settings.page_cache_path)

        for update in updates_data:
            title = update.get("title", "Untitled")
            content = update.get("content", "")
            action = update.get("action", "update")

            # Look up existing page ID from cache
            cached = cache.find_by_title(title)
            page_id = cached.page_id if cached else None

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
        parent_page = cache.find_by_title("Codebase Cortex")
        parent_id = parent_page.page_id if parent_page else None

        try:
            async with notion_mcp_session(settings) as session:
                for update in updates:
                    await rate_limiter.acquire()

                    page_id = update["page_id"]

                    # If no cached page_id, search Notion before creating
                    if not page_id:
                        page_id = await search_page_by_title(
                            session, update["title"]
                        )
                        if page_id:
                            cache.upsert(page_id, update["title"])

                    if page_id:
                        # Fetch current content first, then update
                        await rate_limiter.acquire()
                        try:
                            existing = await session.call_tool(
                                "notion-fetch",
                                arguments={"id": page_id},
                            )
                            # Only update if content actually changed
                            existing_text = ""
                            if not existing.isError and existing.content:
                                existing_text = existing.content[0].text
                        except Exception:
                            existing_text = ""

                        await session.call_tool(
                            "notion-update-page",
                            arguments={
                                "page_id": page_id,
                                "command": "replace_content",
                                "new_str": update["content"],
                            },
                        )
                        cache.upsert(page_id, update["title"])
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
                            cache.upsert(new_page_id, update["title"])
                        logger.info(f"Created: {update['title']}")

        except Exception as e:
            logger.error(f"Failed to write docs to Notion: {e}")
