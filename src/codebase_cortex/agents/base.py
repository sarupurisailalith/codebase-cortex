"""Base agent with LLM invocation via LiteLLM."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

import litellm

from codebase_cortex.config import Settings, get_model_for_node
from codebase_cortex.metrics import RunMetrics
from codebase_cortex.state import CortexState


class BaseAgent(ABC):
    """Base class for all Cortex agents.

    Provides LLM invocation via LiteLLM and optional metrics tracking.
    """

    def __init__(
        self,
        settings: Settings,
        backend: "DocBackend | None" = None,
        metrics: RunMetrics | None = None,
    ) -> None:
        self.settings = settings
        self.backend = backend
        self.metrics = metrics
        self._logger = logging.getLogger("cortex")

    @abstractmethod
    async def run(self, state: CortexState) -> dict:
        """Execute this agent's logic and return state updates."""
        ...

    async def _invoke_llm(
        self,
        messages: list[dict],
        node_name: str = "",
    ) -> str:
        """Invoke the LLM via LiteLLM. Returns response content as plain text.

        Args:
            messages: OpenAI-format message dicts [{"role": ..., "content": ...}].
            node_name: Pipeline node name for per-node model selection and metrics.
        """
        agent_name = self.__class__.__name__
        model = get_model_for_node(self.settings, node_name)

        # Log prompt summary
        total_chars = sum(len(m.get("content", "")) for m in messages)
        self._logger.debug(
            f"LLM CALL [{agent_name}]: model={model}, "
            f"{len(messages)} messages, {total_chars} chars"
        )
        for m in messages:
            preview = str(m.get("content", ""))[:200]
            self._logger.debug(f"  {m.get('role', '?')}: {preview}...")

        kwargs: dict = {
            "model": model,
            "messages": messages,
        }
        if self.settings.llm_api_base:
            kwargs["api_base"] = self.settings.llm_api_base
        if self.settings.llm_api_key:
            kwargs["api_key"] = self.settings.llm_api_key
        if self.settings.llm_fallback:
            kwargs["fallbacks"] = [self.settings.llm_fallback]

        response = await litellm.acompletion(**kwargs)

        content = response.choices[0].message.content

        # Some models return structured content blocks instead of a plain string
        if isinstance(content, list):
            content = "\n".join(
                part["text"] if isinstance(part, dict) else str(part)
                for part in content
                if not isinstance(part, dict) or part.get("type") == "text"
            )

        # Track metrics
        if self.metrics and response.usage:
            self.metrics.record_llm_call(
                node=node_name or agent_name,
                input_tokens=response.usage.prompt_tokens or 0,
                output_tokens=response.usage.completion_tokens or 0,
                cost=self._safe_completion_cost(response),
            )

        self._logger.debug(
            f"LLM RESPONSE [{agent_name}]: {len(content)} chars — {content[:200]}..."
        )
        return content

    @staticmethod
    def _safe_completion_cost(response) -> float:
        """Compute cost via LiteLLM. Returns 0.0 for local/unknown models."""
        try:
            cost = litellm.completion_cost(completion_response=response)
            return cost if cost else 0.0
        except Exception:
            return 0.0

    def _get_mcp_tools(self, state: CortexState) -> list:
        return state.get("mcp_tools", [])

    def _append_error(self, state: CortexState, error: str) -> list[str]:
        errors = list(state.get("errors", []))
        errors.append(f"[{self.__class__.__name__}] {error}")
        return errors
