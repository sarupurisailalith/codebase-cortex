"""SprintReporter agent — generates weekly sprint summaries in Notion."""

from __future__ import annotations

from codebase_cortex.agents.base import BaseAgent
from codebase_cortex.state import CortexState


class SprintReporterAgent(BaseAgent):
    """Generates sprint summary reports in Notion."""

    async def run(self, state: CortexState) -> dict:
        # Placeholder — Week 2 implementation
        return {"sprint_summary": ""}
