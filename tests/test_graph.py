"""Tests for graph construction."""

from __future__ import annotations

from codebase_cortex.graph import build_graph, should_run_docs, should_run_sprint


def test_build_graph():
    graph = build_graph()
    assert graph is not None


def test_should_run_docs_with_analysis():
    assert should_run_docs({"analysis": "some analysis"}) == "semantic_finder"


def test_should_run_docs_without_analysis():
    assert should_run_docs({}) == "end"
    assert should_run_docs({"analysis": ""}) == "end"


def test_should_run_sprint_on_schedule():
    assert should_run_sprint({"trigger": "schedule"}) == "sprint_reporter"


def test_should_run_sprint_on_manual():
    assert should_run_sprint({"trigger": "manual"}) == "end"
