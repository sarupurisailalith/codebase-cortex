"""Base agent with MCP tool access."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage

from codebase_cortex.state import CortexState


class BaseAgent(ABC):
    """Base class for all Cortex agents.

    Provides access to the LLM and MCP tools from state.
    """

    def __init__(self, llm: BaseChatModel) -> None:
        self.llm = llm
        self._logger = logging.getLogger("cortex")

    @abstractmethod
    async def run(self, state: CortexState) -> dict:
        """Execute this agent's logic and return state updates."""
        ...

    async def _invoke_llm(self, messages: list[BaseMessage]) -> str:
        """Invoke the LLM with logging. Returns response content."""
        agent_name = self.__class__.__name__

        # Log prompt summary
        total_chars = sum(len(m.content) for m in messages)
        self._logger.debug(
            f"LLM CALL [{agent_name}]: {len(messages)} messages, {total_chars} chars"
        )
        for m in messages:
            self._logger.debug(
                f"  {m.type}: {m.content[:200]}..."
            )

        response = await self.llm.ainvoke(messages)
        content = response.content

        self._logger.debug(
            f"LLM RESPONSE [{agent_name}]: {len(content)} chars — {content[:200]}..."
        )
        return content

    def _get_mcp_tools(self, state: CortexState) -> list:
        return state.get("mcp_tools", [])

    def _append_error(self, state: CortexState, error: str) -> list[str]:
        errors = list(state.get("errors", []))
        errors.append(f"[{self.__class__.__name__}] {error}")
        return errors
