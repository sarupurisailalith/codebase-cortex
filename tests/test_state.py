"""Tests for state definitions."""

from __future__ import annotations

from codebase_cortex.state import CortexState, FileChange


def test_cortex_state_creation():
    state: CortexState = {
        "trigger": "manual",
        "repo_path": ".",
        "errors": [],
    }
    assert state["trigger"] == "manual"
    assert state["errors"] == []


def test_file_change_creation():
    fc = FileChange(
        path="src/main.py",
        status="modified",
        additions=5,
        deletions=2,
        diff="...",
    )
    assert fc["path"] == "src/main.py"
    assert fc["status"] == "modified"
