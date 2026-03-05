"""SemanticFinder agent — finds related docs via FAISS embedding similarity."""

from __future__ import annotations

from codebase_cortex.agents.base import BaseAgent
from codebase_cortex.state import CortexState


class SemanticFinderAgent(BaseAgent):
    """Finds semantically related documentation using embeddings."""

    async def run(self, state: CortexState) -> dict:
        # Placeholder — Week 2 implementation
        return {"related_docs": []}
