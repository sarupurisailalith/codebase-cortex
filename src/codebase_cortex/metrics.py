"""RunMetrics — per-run observability and cost tracking."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class NodeMetrics:
    """Metrics for a single pipeline node."""

    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    wall_clock_seconds: float = 0.0
    counters: dict[str, int] = field(default_factory=dict)
    _start_time: float | None = field(default=None, repr=False)


@dataclass
class RunMetrics:
    """Collects metrics across all pipeline nodes for a single run."""

    start_time: float = field(default_factory=time.time)
    source_commit: str = ""
    trigger: str = "manual"
    detail_level: str = "standard"

    # Aggregate
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    wall_clock_seconds: float = 0.0

    # Section stats
    sections_analyzed: int = 0
    sections_updated: int = 0
    sections_human_edited: int = 0
    sections_skipped_no_change: int = 0

    # Validation
    validation_confidence: dict[str, int] = field(
        default_factory=lambda: {"high": 0, "medium": 0, "low": 0}
    )

    # Per-node
    by_node: dict[str, NodeMetrics] = field(default_factory=dict)

    def record_llm_call(
        self,
        node: str,
        input_tokens: int,
        output_tokens: int,
        cost: float = 0.0,
    ) -> None:
        """Record an LLM call's token usage and cost."""
        nm = self.by_node.setdefault(node, NodeMetrics())
        nm.input_tokens += input_tokens
        nm.output_tokens += output_tokens
        nm.estimated_cost_usd += cost

        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.estimated_cost_usd += cost

    def start_node(self, node: str) -> None:
        """Mark the start of a pipeline node's execution."""
        nm = self.by_node.setdefault(node, NodeMetrics())
        nm._start_time = time.time()

    def end_node(self, node: str) -> None:
        """Mark the end of a pipeline node's execution."""
        nm = self.by_node.get(node)
        if nm and nm._start_time is not None:
            nm.wall_clock_seconds += time.time() - nm._start_time
            nm._start_time = None

    def finalize(self) -> dict:
        """Compute final metrics and return a JSON-serializable dict."""
        self.wall_clock_seconds = time.time() - self.start_time

        by_node_dict = {}
        for name, nm in self.by_node.items():
            by_node_dict[name] = {
                "input_tokens": nm.input_tokens,
                "output_tokens": nm.output_tokens,
                "estimated_cost_usd": round(nm.estimated_cost_usd, 6),
                "wall_clock_seconds": round(nm.wall_clock_seconds, 2),
                "counters": nm.counters,
            }

        return {
            "source_commit": self.source_commit,
            "trigger": self.trigger,
            "detail_level": self.detail_level,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "estimated_cost_usd": round(self.estimated_cost_usd, 6),
            "wall_clock_seconds": round(self.wall_clock_seconds, 2),
            "sections_analyzed": self.sections_analyzed,
            "sections_updated": self.sections_updated,
            "sections_human_edited": self.sections_human_edited,
            "sections_skipped_no_change": self.sections_skipped_no_change,
            "validation_confidence": self.validation_confidence,
            "by_node": by_node_dict,
        }

    def append_to_history(self, cortex_dir: Path) -> None:
        """Append finalized metrics to .cortex/run_history.jsonl."""
        history_path = cortex_dir / "run_history.jsonl"
        data = self.finalize()
        data["timestamp"] = time.time()
        with open(history_path, "a") as f:
            f.write(json.dumps(data) + "\n")
