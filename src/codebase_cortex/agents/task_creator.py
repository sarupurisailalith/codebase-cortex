"""TaskCreator agent — creates Notion tasks for undocumented areas."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from codebase_cortex.agents.base import BaseAgent
from codebase_cortex.notion.bootstrap import extract_page_id
from codebase_cortex.state import CortexState, TaskItem
from codebase_cortex.utils.json_parsing import parse_json_array

SYSTEM_PROMPT = """You are a documentation quality analyst. Given a code analysis,
identify areas that need documentation but don't have it yet.

Output a JSON array of tasks, each with:
- "title": Brief task title (imperative form, e.g., "Document the auth flow")
- "description": What needs to be documented and why
- "priority": "high" (breaking changes, new APIs), "medium" (new features), or "low" (refactors, minor changes)

Only create tasks for genuinely undocumented or under-documented areas.
Don't create tasks for trivial changes (formatting, typos, minor refactors).
Respond with ONLY the JSON array. If nothing needs documenting, return []."""


class TaskCreatorAgent(BaseAgent):
    """Creates tasks in Notion for areas needing documentation."""

    async def run(self, state: CortexState) -> dict:
        analysis = state.get("analysis", "")
        if not analysis:
            return {"tasks_created": []}

        doc_updates = state.get("doc_updates", [])
        dry_run = state.get("dry_run", False)

        # Build context about what was already documented
        already_documented = ""
        if doc_updates:
            already_documented = "\n\n## Already Documented\nThe following pages were just updated:\n"
            for d in doc_updates:
                already_documented += f"- {d['title']} ({d['action']})\n"

        prompt = f"""Review this code analysis and identify documentation gaps.

## Code Analysis
{analysis}
{already_documented}

Create tasks only for areas NOT already covered by the doc updates above.
Respond with a JSON array of tasks (title, description, priority). Return [] if all areas are covered."""

        try:
            messages = [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ]
            response = await self.llm.ainvoke(messages)
            raw = response.content

            tasks_data = parse_json_array(raw)

        except Exception as e:
            return {
                "tasks_created": [],
                "errors": self._append_error(state, f"Task creation failed: {e}"),
            }

        tasks: list[TaskItem] = [
            TaskItem(
                title=t.get("title", "Untitled task"),
                description=t.get("description", ""),
                priority=t.get("priority", "medium"),
            )
            for t in tasks_data
        ]

        # Create tasks in Notion (unless dry_run)
        if not dry_run and tasks:
            await self._create_in_notion(tasks, state)

        return {"tasks_created": tasks}

    async def _create_in_notion(self, tasks: list[TaskItem], state: CortexState) -> None:
        """Create task items in Notion via MCP."""
        from codebase_cortex.mcp_client import notion_mcp_session, rate_limiter
        from codebase_cortex.config import Settings
        from codebase_cortex.notion.page_cache import PageCache
        from codebase_cortex.utils.logging import get_logger

        logger = get_logger()
        settings = Settings.from_env()
        cache = PageCache(cache_path=settings.page_cache_path)

        # Find parent page and task board for organization
        parent_page = cache.find_by_title("Codebase Cortex")
        task_board = cache.find_by_title("Task Board")
        parent_id = (task_board or parent_page)
        parent_id = parent_id.page_id if parent_id else None

        try:
            async with notion_mcp_session(settings) as session:
                for task in tasks:
                    await rate_limiter.acquire()

                    priority_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(
                        task["priority"], "⚪"
                    )

                    title = f"{priority_icon} {task['title']}"
                    content = (
                        f"## {task['title']}\n\n"
                        f"**Priority:** {task['priority']}\n\n"
                        f"{task['description']}\n\n"
                        f"---\n*Auto-created by Codebase Cortex*"
                    )

                    create_args: dict = {
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

                    page_id = extract_page_id(result)
                    if page_id:
                        cache.upsert(page_id, task["title"])

                    logger.info(f"Created task: {priority_icon} {task['title']}")

                # Append a summary list to the Task Board page itself
                if task_board:
                    await rate_limiter.acquire()
                    from datetime import datetime

                    date_label = datetime.now().strftime("%Y-%m-%d")
                    summary_lines = [f"\n\n---\n\n### Tasks — {date_label}\n"]
                    for task in tasks:
                        icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(
                            task["priority"], "⚪"
                        )
                        summary_lines.append(f"- {icon} **{task['title']}** — {task['description'][:80]}")

                    try:
                        await session.call_tool(
                            "notion-update-page",
                            arguments={
                                "page_id": task_board.page_id,
                                "command": "insert_content_after",
                                "selection_with_ellipsis": "---\n*Auto-gen...by Codebase Cortex*",
                                "new_str": "\n".join(summary_lines),
                            },
                        )
                    except Exception:
                        # Fallback: try appending without selection match
                        try:
                            await session.call_tool(
                                "notion-update-page",
                                arguments={
                                    "page_id": task_board.page_id,
                                    "command": "insert_content_after",
                                    "selection_with_ellipsis": "...",
                                    "new_str": "\n".join(summary_lines),
                                },
                            )
                        except Exception as append_err:
                            logger.warning(f"Could not append task summary to Task Board: {append_err}")

        except Exception as e:
            logger.error(f"Failed to create tasks in Notion: {e}")
