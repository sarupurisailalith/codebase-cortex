"""Tests for config module."""

from __future__ import annotations

from codebase_cortex.config import Settings


def test_settings_defaults():
    s = Settings()
    assert s.llm_provider == "google"
    assert s.repo_path == "."
    assert s.oauth_callback_port == 9876


def test_settings_custom():
    s = Settings(llm_provider="anthropic", repo_path="/tmp/repo")
    assert s.llm_provider == "anthropic"
    assert s.repo_path == "/tmp/repo"
