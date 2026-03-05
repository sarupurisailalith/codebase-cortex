"""Tests for agent implementations."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from codebase_cortex.agents.base import BaseAgent
from codebase_cortex.agents.code_analyzer import CodeAnalyzerAgent
from codebase_cortex.agents.doc_writer import DocWriterAgent
from codebase_cortex.agents.task_creator import TaskCreatorAgent
from codebase_cortex.agents.sprint_reporter import SprintReporterAgent


def _make_mock_llm(response_content: str) -> MagicMock:
    """Create a mock LLM that returns the given content."""
    mock = MagicMock()
    mock_response = MagicMock()
    mock_response.content = response_content
    mock.ainvoke = AsyncMock(return_value=mock_response)
    return mock


# --- BaseAgent tests ---


def test_base_agent_is_abstract():
    with pytest.raises(TypeError):
        BaseAgent(llm=MagicMock())  # type: ignore


def test_append_error():
    class TestAgent(BaseAgent):
        async def run(self, state):
            return {}

    agent = TestAgent(llm=MagicMock())
    errors = agent._append_error({"errors": ["existing"]}, "new error")
    assert len(errors) == 2
    assert "[TestAgent] new error" in errors[1]


# --- CodeAnalyzer tests ---


@pytest.mark.asyncio
async def test_code_analyzer_with_diff():
    mock_llm = _make_mock_llm("## Summary\nFiles were modified.")
    agent = CodeAnalyzerAgent(mock_llm)

    state = {
        "trigger": "manual",
        "repo_path": ".",
        "diff_text": "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-old\n+new",
        "errors": [],
    }

    result = await agent.run(state)
    assert result["analysis"] == "## Summary\nFiles were modified."
    assert len(result["changed_files"]) == 1


@pytest.mark.asyncio
async def test_code_analyzer_empty_diff(tmp_path):
    # Use a non-git directory so get_recent_diff fails gracefully
    agent = CodeAnalyzerAgent(_make_mock_llm(""))
    result = await agent.run({"diff_text": "", "repo_path": str(tmp_path), "errors": []})
    # tmp_path has no .git, so get_recent_diff raises and we get an error
    assert "errors" in result


# --- DocWriter tests ---


@pytest.mark.asyncio
async def test_doc_writer_generates_updates():
    response = json.dumps([
        {"title": "Architecture Overview", "content": "# Updated arch", "action": "update"},
    ])
    agent = DocWriterAgent(_make_mock_llm(response))

    state = {
        "analysis": "New auth module added",
        "related_docs": [],
        "dry_run": True,
        "errors": [],
    }

    result = await agent.run(state)
    assert len(result["doc_updates"]) == 1
    assert result["doc_updates"][0]["title"] == "Architecture Overview"
    assert result["doc_updates"][0]["action"] == "update"


@pytest.mark.asyncio
async def test_doc_writer_no_analysis():
    agent = DocWriterAgent(_make_mock_llm(""))
    result = await agent.run({"analysis": "", "errors": []})
    assert result["doc_updates"] == []


# --- TaskCreator tests ---


@pytest.mark.asyncio
async def test_task_creator_generates_tasks():
    response = json.dumps([
        {"title": "Document auth flow", "description": "Auth module lacks docs", "priority": "high"},
        {"title": "Add API examples", "description": "Endpoints need examples", "priority": "medium"},
    ])
    agent = TaskCreatorAgent(_make_mock_llm(response))

    state = {
        "analysis": "New auth module with 3 endpoints",
        "doc_updates": [],
        "dry_run": True,
        "errors": [],
    }

    result = await agent.run(state)
    assert len(result["tasks_created"]) == 2
    assert result["tasks_created"][0]["priority"] == "high"


@pytest.mark.asyncio
async def test_task_creator_no_analysis():
    agent = TaskCreatorAgent(_make_mock_llm(""))
    result = await agent.run({"analysis": "", "errors": []})
    assert result["tasks_created"] == []


# --- SprintReporter tests ---


@pytest.mark.asyncio
async def test_sprint_reporter_generates_summary():
    agent = SprintReporterAgent(_make_mock_llm("## Sprint Overview\nGood progress this week."))

    state = {
        "analysis": "Several files updated",
        "changed_files": [{"additions": 10, "deletions": 5}],
        "doc_updates": [{"title": "API Ref", "action": "update"}],
        "tasks_created": [{"title": "Doc auth", "priority": "high"}],
        "dry_run": True,
        "errors": [],
    }

    result = await agent.run(state)
    assert "Sprint Overview" in result["sprint_summary"]


@pytest.mark.asyncio
async def test_sprint_reporter_no_analysis():
    agent = SprintReporterAgent(_make_mock_llm(""))
    result = await agent.run({"analysis": "", "errors": []})
    assert result["sprint_summary"] == ""
