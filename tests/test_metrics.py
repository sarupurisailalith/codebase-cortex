"""Tests for RunMetrics collector."""

from __future__ import annotations

import json
import time

from codebase_cortex.metrics import RunMetrics, NodeMetrics


def test_run_metrics_defaults():
    m = RunMetrics()
    assert m.total_input_tokens == 0
    assert m.total_output_tokens == 0
    assert m.estimated_cost_usd == 0.0
    assert m.sections_analyzed == 0
    assert m.by_node == {}
    assert m.validation_confidence == {"high": 0, "medium": 0, "low": 0}


def test_record_llm_call():
    m = RunMetrics()
    m.record_llm_call("code_analyzer", input_tokens=100, output_tokens=50, cost=0.001)
    m.record_llm_call("code_analyzer", input_tokens=200, output_tokens=100, cost=0.002)

    assert m.total_input_tokens == 300
    assert m.total_output_tokens == 150
    assert m.estimated_cost_usd == pytest.approx(0.003)
    assert m.by_node["code_analyzer"].input_tokens == 300
    assert m.by_node["code_analyzer"].output_tokens == 150


def test_record_llm_call_multiple_nodes():
    m = RunMetrics()
    m.record_llm_call("code_analyzer", input_tokens=100, output_tokens=50)
    m.record_llm_call("doc_writer", input_tokens=200, output_tokens=100)

    assert m.total_input_tokens == 300
    assert len(m.by_node) == 2


def test_start_end_node():
    m = RunMetrics()
    m.start_node("code_analyzer")
    time.sleep(0.01)  # Small delay to get measurable time
    m.end_node("code_analyzer")

    assert m.by_node["code_analyzer"].wall_clock_seconds > 0


def test_finalize():
    m = RunMetrics(source_commit="abc123", trigger="ci", detail_level="detailed")
    m.record_llm_call("code_analyzer", input_tokens=100, output_tokens=50, cost=0.001)
    m.sections_updated = 3
    m.sections_analyzed = 10

    result = m.finalize()
    assert result["source_commit"] == "abc123"
    assert result["trigger"] == "ci"
    assert result["detail_level"] == "detailed"
    assert result["total_input_tokens"] == 100
    assert result["total_output_tokens"] == 50
    assert result["sections_updated"] == 3
    assert result["sections_analyzed"] == 10
    assert "code_analyzer" in result["by_node"]
    assert result["wall_clock_seconds"] >= 0


def test_finalize_is_json_serializable():
    m = RunMetrics()
    m.record_llm_call("test", input_tokens=10, output_tokens=5)
    result = m.finalize()
    # Should not raise
    json.dumps(result)


def test_append_to_history(tmp_path):
    m = RunMetrics(source_commit="abc123")
    m.record_llm_call("test", input_tokens=10, output_tokens=5)

    m.append_to_history(tmp_path)

    history_file = tmp_path / "run_history.jsonl"
    assert history_file.exists()

    line = history_file.read_text().strip()
    data = json.loads(line)
    assert data["source_commit"] == "abc123"
    assert "timestamp" in data


def test_append_to_history_appends(tmp_path):
    m1 = RunMetrics(source_commit="abc")
    m1.append_to_history(tmp_path)
    m2 = RunMetrics(source_commit="def")
    m2.append_to_history(tmp_path)

    lines = (tmp_path / "run_history.jsonl").read_text().strip().split("\n")
    assert len(lines) == 2


# Need pytest for approx
import pytest
