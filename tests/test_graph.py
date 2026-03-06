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


def test_should_run_sprint_with_updates():
    assert should_run_sprint({"doc_updates": [{"title": "x"}]}) == "sprint_reporter"
    assert should_run_sprint({"tasks_created": [{"title": "y"}]}) == "sprint_reporter"


def test_should_run_sprint_no_updates():
    assert should_run_sprint({}) == "end"
    assert should_run_sprint({"doc_updates": [], "tasks_created": []}) == "end"
