"""TaskCreator agent — creates tasks for undocumented areas via DocBackend."""

from __future__ import annotations

from codebase_cortex.agents.base import BaseAgent
from codebase_cortex.backends import get_backend
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
    """Creates tasks for undocumented areas via DocBackend."""

    async def run(self, state: CortexState) -> dict:
        analysis = state.get("analysis", "")
        if not analysis:
            return {"tasks_created": []}

        doc_updates = state.get("validated_updates", state.get("doc_updates", []))
        validation_issues = state.get("validation_issues", [])
        dry_run = state.get("dry_run", False)

        backend = self.backend or get_backend(self.settings)

        # Build context about what was already documented
        already_documented = ""
        if doc_updates:
            already_documented = "\n\n## Already Documented\nThe following pages were just updated:\n"
            for d in doc_updates:
                already_documented += f"- {d.get('title', 'Untitled')} ({d.get('action', 'update')})\n"

        prompt = f"""Review this code analysis and identify documentation gaps.

## Code Analysis
{analysis}
{already_documented}

Create tasks only for areas NOT already covered by the doc updates above.
Respond with a JSON array of tasks (title, description, priority). Return [] if all areas are covered."""

        try:
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
            raw = await self._invoke_llm(messages, node_name="task_creator")
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

        # Add tasks from validation issues (low-confidence sections)
        for issue in validation_issues:
            if issue.get("action") == "excluded":
                page = issue.get("page", "Unknown")
                tasks.append(TaskItem(
                    title=f"Review documentation for {page}",
                    description=(
                        "Automated documentation generation flagged potential inaccuracies. "
                        f"Issues: {', '.join(issue.get('issues', []))}"
                    ),
                    priority="high",
                ))

        # Write tasks via backend
        if not dry_run and tasks:
            for task in tasks:
                try:
                    await backend.create_task(dict(task))
                except Exception as e:
                    self._logger.warning(f"Failed to create task '{task['title']}': {e}")

        return {"tasks_created": tasks}
