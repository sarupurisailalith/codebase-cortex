"""OutputRouter — final pipeline node for mode-based delivery of results."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from codebase_cortex.config import Settings
from codebase_cortex.state import CortexState

logger = logging.getLogger("cortex")


class OutputRouterAgent:
    """Final pipeline node that delivers results based on output_mode.

    Modes:
    - apply: writes already done by DocWriter — just log summary
    - propose: stage changes to .cortex/proposed/, undo docs/ writes
    - dry-run: print summary, write nothing
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings

    async def run(self, state: CortexState) -> dict:
        output_mode = state.get("output_mode", "apply")
        settings = self.settings or Settings.from_env()

        updates = state.get("validated_updates", state.get("doc_updates", []))
        tasks = state.get("tasks_created", [])
        sprint = state.get("sprint_summary", "")

        if output_mode == "dry-run":
            return self._dry_run(updates, tasks, sprint, state)
        elif output_mode == "propose":
            return self._propose(updates, tasks, settings, state)
        else:
            return self._apply(updates, tasks, sprint, state)

    def _apply(
        self,
        updates: list[dict],
        tasks: list[dict],
        sprint: str,
        state: CortexState,
    ) -> dict:
        """Apply mode — writes already happened. Just log the summary."""
        summary_lines = ["## Pipeline Summary (apply mode)", ""]

        if updates:
            summary_lines.append(f"**Documentation:** {len(updates)} page(s) updated")
            for u in updates:
                confidence = u.get("confidence", "—")
                summary_lines.append(f"  - {u.get('title', '?')} ({u.get('action', '?')}) [confidence: {confidence}]")

        if tasks:
            summary_lines.append(f"**Tasks:** {len(tasks)} task(s) created")

        if sprint:
            summary_lines.append("**Sprint report:** generated")

        summary = "\n".join(summary_lines)
        logger.info(summary)
        return {"output_summary": summary}

    def _propose(
        self,
        updates: list[dict],
        tasks: list[dict],
        settings: Settings,
        state: CortexState,
    ) -> dict:
        """Propose mode — copy changes to .cortex/proposed/."""
        proposed_dir = settings.cortex_dir / "proposed"
        proposed_dir.mkdir(parents=True, exist_ok=True)

        docs_dir = Path(settings.repo_path) / "docs"

        # Copy modified doc files to proposed/
        for update in updates:
            page_path = update.get("page_path", "")
            if not page_path:
                continue
            src = docs_dir / page_path
            if src.exists():
                dst = proposed_dir / page_path
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)

        summary = (
            f"Changes staged to {proposed_dir}.\n"
            f"  {len(updates)} page(s), {len(tasks)} task(s).\n"
            "Run `cortex diff` to review, `cortex apply` to accept."
        )
        logger.info(summary)
        return {"output_summary": summary}

    def _dry_run(
        self,
        updates: list[dict],
        tasks: list[dict],
        sprint: str,
        state: CortexState,
    ) -> dict:
        """Dry-run mode — print what would happen, write nothing."""
        summary_lines = ["## Pipeline Summary (dry-run mode)", ""]
        summary_lines.append("No changes were written to disk.", )

        if updates:
            summary_lines.append(f"\n**Would update {len(updates)} page(s):**")
            for u in updates:
                summary_lines.append(f"  - {u.get('title', '?')} ({u.get('action', '?')})")

        if tasks:
            summary_lines.append(f"\n**Would create {len(tasks)} task(s):**")
            for t in tasks:
                summary_lines.append(f"  - [{t.get('priority', '?')}] {t.get('title', '?')}")

        metrics = state.get("run_metrics", {})
        if metrics:
            tokens_in = metrics.get("total_input_tokens", 0)
            tokens_out = metrics.get("total_output_tokens", 0)
            cost = metrics.get("estimated_cost_usd", 0)
            summary_lines.append(f"\n**Metrics:** {tokens_in} input tokens, {tokens_out} output tokens, ${cost:.4f}")

        summary = "\n".join(summary_lines)
        logger.info(summary)
        return {"output_summary": summary}
