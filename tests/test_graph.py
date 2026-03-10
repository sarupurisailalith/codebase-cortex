"""Tests for graph construction."""

from __future__ import annotations

from codebase_cortex.graph import (
    build_graph,
    should_run_section_router,
    should_run_doc_writer,
    should_run_validator,
    should_run_sprint,
)


def test_build_graph():
    graph = build_graph()
    assert graph is not None


def test_should_run_section_router_with_analysis():
    assert should_run_section_router({"analysis": "some analysis"}) == "semantic_finder"


def test_should_run_section_router_without_analysis():
    assert should_run_section_router({}) == "end"
    assert should_run_section_router({"analysis": ""}) == "end"


def test_should_run_doc_writer_with_sections():
    assert should_run_doc_writer({"targeted_sections": [{"page": "a.md"}]}) == "doc_writer"


def test_should_run_doc_writer_without_sections():
    assert should_run_doc_writer({}) == "end"
    assert should_run_doc_writer({"targeted_sections": []}) == "end"


def test_should_run_validator_standard():
    assert should_run_validator({"detail_level": "standard"}) == "toc_generator"
    assert should_run_validator({}) == "toc_generator"


def test_should_run_validator_detailed():
    assert should_run_validator({"detail_level": "detailed"}) == "doc_validator"
    assert should_run_validator({"detail_level": "comprehensive"}) == "doc_validator"


def test_should_run_sprint_with_updates():
    assert should_run_sprint({"doc_updates": [{"title": "x"}]}) == "sprint_reporter"
    assert should_run_sprint({"tasks_created": [{"title": "y"}]}) == "sprint_reporter"
    assert should_run_sprint({"validated_updates": [{}]}) == "sprint_reporter"


def test_should_run_sprint_no_updates():
    assert should_run_sprint({}) == "end"
    assert should_run_sprint({"doc_updates": [], "tasks_created": []}) == "end"
