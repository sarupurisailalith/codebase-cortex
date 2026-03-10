"""Tests for agent implementations."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from codebase_cortex.agents.base import BaseAgent
from codebase_cortex.agents.code_analyzer import CodeAnalyzerAgent
from codebase_cortex.agents.doc_writer import DocWriterAgent
from codebase_cortex.agents.task_creator import TaskCreatorAgent
from codebase_cortex.agents.sprint_reporter import SprintReporterAgent
from codebase_cortex.config import Settings


def _make_mock_settings() -> Settings:
    """Create a Settings instance for testing."""
    return Settings(llm_model="google/gemini-2.5-flash-lite")


def _patch_litellm(response_content: str):
    """Create a patch for litellm.acompletion that returns the given content."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = response_content
    mock_response.usage = MagicMock()
    mock_response.usage.prompt_tokens = 100
    mock_response.usage.completion_tokens = 50
    return patch("litellm.acompletion", new_callable=AsyncMock, return_value=mock_response)


# --- BaseAgent tests ---


def test_base_agent_is_abstract():
    with pytest.raises(TypeError):
        BaseAgent(settings=_make_mock_settings())  # type: ignore


def test_append_error():
    class TestAgent(BaseAgent):
        async def run(self, state):
            return {}

    agent = TestAgent(settings=_make_mock_settings())
    errors = agent._append_error({"errors": ["existing"]}, "new error")
    assert len(errors) == 2
    assert "[TestAgent] new error" in errors[1]


# --- CodeAnalyzer tests ---


@pytest.mark.asyncio
async def test_code_analyzer_with_diff():
    with _patch_litellm("## Summary\nFiles were modified."):
        agent = CodeAnalyzerAgent(_make_mock_settings())

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
    with _patch_litellm(""):
        agent = CodeAnalyzerAgent(_make_mock_settings())
        result = await agent.run({"diff_text": "", "repo_path": str(tmp_path), "errors": []})
        # tmp_path has no .git, so get_recent_diff raises and we get an error
        assert "errors" in result


# --- DocWriter tests ---


@pytest.mark.asyncio
async def test_doc_writer_generates_updates():
    response = "Updated content for the overview section."
    with _patch_litellm(response):
        agent = DocWriterAgent(_make_mock_settings())

        state = {
            "analysis": "New auth module added",
            "related_docs": [],
            "dry_run": True,
            "targeted_sections": [
                {"page": "architecture.md", "section": "## Overview", "reason": "Auth changed", "priority": "high"},
            ],
            "errors": [],
        }

        result = await agent.run(state)
        assert len(result["doc_updates"]) == 1
        assert result["doc_updates"][0]["action"] == "update"
        assert "architecture.md" in result["doc_updates"][0]["page_path"]


@pytest.mark.asyncio
async def test_doc_writer_no_analysis():
    with _patch_litellm(""):
        agent = DocWriterAgent(_make_mock_settings())
        result = await agent.run({"analysis": "", "errors": []})
        assert result["doc_updates"] == []


# --- TaskCreator tests ---


@pytest.mark.asyncio
async def test_task_creator_generates_tasks():
    response = json.dumps([
        {"title": "Document auth flow", "description": "Auth module lacks docs", "priority": "high"},
        {"title": "Add API examples", "description": "Endpoints need examples", "priority": "medium"},
    ])
    with _patch_litellm(response):
        agent = TaskCreatorAgent(_make_mock_settings())

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
    with _patch_litellm(""):
        agent = TaskCreatorAgent(_make_mock_settings())
        result = await agent.run({"analysis": "", "errors": []})
        assert result["tasks_created"] == []


# --- SprintReporter tests ---


@pytest.mark.asyncio
async def test_sprint_reporter_generates_summary():
    with _patch_litellm("## Sprint Overview\nGood progress this week."):
        agent = SprintReporterAgent(_make_mock_settings())

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
    with _patch_litellm(""):
        agent = SprintReporterAgent(_make_mock_settings())
        result = await agent.run({"analysis": "", "errors": []})
        assert result["sprint_summary"] == ""


# --- JSON parsing tests ---


def test_parse_json_array_raw():
    from codebase_cortex.utils.json_parsing import parse_json_array

    result = parse_json_array('[{"title": "test"}]')
    assert result == [{"title": "test"}]


def test_parse_json_array_code_block():
    from codebase_cortex.utils.json_parsing import parse_json_array

    raw = '```json\n[{"title": "test"}]\n```'
    result = parse_json_array(raw)
    assert result == [{"title": "test"}]


def test_parse_json_array_with_surrounding_text():
    from codebase_cortex.utils.json_parsing import parse_json_array

    raw = 'Here are the updates:\n[{"title": "test"}]\nDone.'
    result = parse_json_array(raw)
    assert result == [{"title": "test"}]


def test_parse_json_array_trailing_comma():
    from codebase_cortex.utils.json_parsing import parse_json_array

    raw = '[{"title": "test"},]'
    result = parse_json_array(raw)
    assert result == [{"title": "test"}]


def test_parse_json_array_invalid():
    from codebase_cortex.utils.json_parsing import parse_json_array

    with pytest.raises(ValueError):
        parse_json_array("not json at all")
