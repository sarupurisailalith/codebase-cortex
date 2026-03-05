"""Base agent with MCP tool access."""

from __future__ import annotations

from abc import ABC, abstractmethod

from langchain_core.language_models import BaseChatModel

from codebase_cortex.state import CortexState


class BaseAgent(ABC):
    """Base class for all Cortex agents.

    Provides access to the LLM and MCP tools from state.
    """

    def __init__(self, llm: BaseChatModel) -> None:
        self.llm = llm

    @abstractmethod
    async def run(self, state: CortexState) -> dict:
        """Execute this agent's logic and return state updates.

        Args:
            state: The current pipeline state.

        Returns:
            Dict of state fields to update.
        """
        ...

    def _get_mcp_tools(self, state: CortexState) -> list:
        """Extract MCP tools from state."""
        return state.get("mcp_tools", [])

    def _append_error(self, state: CortexState, error: str) -> list[str]:
        """Create updated error list with a new error appended."""
        errors = list(state.get("errors", []))
        errors.append(f"[{self.__class__.__name__}] {error}")
        return errors
