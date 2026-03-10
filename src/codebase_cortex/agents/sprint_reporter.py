"""SprintReporter agent — generates sprint summaries via DocBackend."""

from __future__ import annotations

from datetime import datetime, timedelta

from codebase_cortex.agents.base import BaseAgent
from codebase_cortex.backends import get_backend
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
    """Generates sprint summary reports via DocBackend."""

    async def run(self, state: CortexState) -> dict:
        analysis = state.get("analysis", "")
        if not analysis:
            return {"sprint_summary": ""}

        changed_files = state.get("changed_files", [])
        doc_updates = state.get("validated_updates", state.get("doc_updates", []))
        tasks_created = state.get("tasks_created", [])
        run_metrics = state.get("run_metrics", {})
        dry_run = state.get("dry_run", False)

        backend = self.backend or get_backend(self.settings)

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
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
            sprint_summary = await self._invoke_llm(messages, node_name="sprint_reporter")
        except Exception as e:
            return {
                "sprint_summary": "",
                "errors": self._append_error(state, f"Sprint report failed: {e}"),
            }

        # Append Cortex usage metrics section
        if run_metrics:
            metrics_section = self._format_metrics(run_metrics)
            sprint_summary += f"\n\n{metrics_section}"

        # Write via backend
        if not dry_run and sprint_summary:
            try:
                await backend.append_to_log("sprint-log.md", sprint_summary)
            except Exception as e:
                self._logger.warning(f"Failed to write sprint report: {e}")

        return {"sprint_summary": sprint_summary}

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

    @staticmethod
    def _format_metrics(metrics: dict) -> str:
        tokens_in = metrics.get("total_input_tokens", 0)
        tokens_out = metrics.get("total_output_tokens", 0)
        total = tokens_in + tokens_out
        cost = metrics.get("estimated_cost_usd", 0)
        wall_clock = metrics.get("wall_clock_seconds", 0)
        sections_updated = metrics.get("sections_updated", 0)
        sections_analyzed = metrics.get("sections_analyzed", 0)

        return (
            "## Cortex Usage\n"
            f"- **Tokens:** {tokens_in:,} input + {tokens_out:,} output = {total:,} total\n"
            f"- **Estimated Cost:** ~${cost:.4f}\n"
            f"- **Pipeline Time:** {wall_clock:.1f}s\n"
            f"- **Sections:** {sections_updated} updated, {sections_analyzed} analyzed"
        )
