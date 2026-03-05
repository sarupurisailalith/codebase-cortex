"""SprintReporter agent — generates weekly sprint summaries in Notion."""

from __future__ import annotations

from datetime import datetime, timedelta

from langchain_core.messages import HumanMessage, SystemMessage

from codebase_cortex.agents.base import BaseAgent
from codebase_cortex.state import CortexState

SYSTEM_PROMPT = """You are a technical project manager writing a sprint summary.
Given code analysis data and documentation updates, write a concise weekly sprint report.

Structure the report with these sections:
1. **Sprint Overview** - One paragraph summary
2. **Key Changes** - Bullet list of significant changes
3. **Documentation Updates** - What docs were created/updated
4. **Open Tasks** - Tasks created for documentation gaps
5. **Metrics** - Files changed, docs updated, tasks created

Keep it professional and concise. Use markdown formatting."""


class SprintReporterAgent(BaseAgent):
    """Generates sprint summary reports in Notion."""

    async def run(self, state: CortexState) -> dict:
        analysis = state.get("analysis", "")
        if not analysis:
            return {"sprint_summary": ""}

        changed_files = state.get("changed_files", [])
        doc_updates = state.get("doc_updates", [])
        tasks_created = state.get("tasks_created", [])
        dry_run = state.get("dry_run", False)

        now = datetime.now()
        week_start = now - timedelta(days=now.weekday())

        prompt = f"""Generate a sprint summary for the week of {week_start.strftime('%B %d, %Y')}.

## Code Analysis
{analysis}

## Changes
- {len(changed_files)} files changed
- {sum(f.get('additions', 0) for f in changed_files)} lines added
- {sum(f.get('deletions', 0) for f in changed_files)} lines deleted

## Documentation Updates
{self._format_doc_updates(doc_updates)}

## Tasks Created
{self._format_tasks(tasks_created)}

Write a complete sprint report in markdown."""

        try:
            messages = [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ]
            response = await self.llm.ainvoke(messages)
            sprint_summary = response.content
        except Exception as e:
            return {
                "sprint_summary": "",
                "errors": self._append_error(state, f"Sprint report failed: {e}"),
            }

        # Write to Notion Sprint Log page
        if not dry_run and sprint_summary:
            await self._write_to_notion(sprint_summary, week_start, state)

        return {"sprint_summary": sprint_summary}

    async def _write_to_notion(
        self, summary: str, week_start: datetime, state: CortexState
    ) -> None:
        """Append sprint summary to the Sprint Log page in Notion."""
        from codebase_cortex.mcp_client import notion_mcp_session, rate_limiter
        from codebase_cortex.config import Settings
        from codebase_cortex.notion.page_cache import PageCache
        from codebase_cortex.utils.logging import get_logger

        logger = get_logger()
        settings = Settings.from_env()
        cache = PageCache(cache_path=settings.page_cache_path)

        sprint_page = cache.find_by_title("Sprint Log")

        try:
            async with notion_mcp_session(settings) as session:
                await rate_limiter.acquire()

                week_label = week_start.strftime("%B %d, %Y")
                content = f"# Sprint Report — Week of {week_label}\n\n{summary}"

                if sprint_page:
                    await session.call_tool(
                        "notion_update_page",
                        arguments={
                            "page_id": sprint_page.page_id,
                            "content": content,
                        },
                    )
                    logger.info(f"Updated Sprint Log for week of {week_label}")
                else:
                    await session.call_tool(
                        "notion_create_page",
                        arguments={
                            "title": f"Sprint Report — {week_label}",
                            "content": content,
                        },
                    )
                    logger.info(f"Created Sprint Report for week of {week_label}")

        except Exception as e:
            logger.error(f"Failed to write sprint report: {e}")

    @staticmethod
    def _format_doc_updates(updates: list[dict]) -> str:
        if not updates:
            return "No documentation updates this sprint."
        return "\n".join(f"- {u.get('title', 'Untitled')} ({u.get('action', 'update')})" for u in updates)

    @staticmethod
    def _format_tasks(tasks: list[dict]) -> str:
        if not tasks:
            return "No new tasks created."
        return "\n".join(
            f"- [{t.get('priority', 'medium')}] {t.get('title', 'Untitled')}" for t in tasks
        )
