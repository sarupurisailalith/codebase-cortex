"""Tests for config module."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from codebase_cortex.config import Settings, CORTEX_DIR_NAME


ENV_KEYS = [
    "LLM_PROVIDER", "LLM_MODEL", "GOOGLE_API_KEY",
    "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "GITHUB_TOKEN",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Remove LLM-related env vars before each test to prevent leaking."""
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_settings_defaults():
    s = Settings()
    assert s.llm_provider == "google"
    assert s.llm_model == ""
    assert s.openrouter_api_key == ""
    assert s.oauth_callback_port == 9876


def test_settings_custom():
    s = Settings(llm_provider="anthropic", repo_path=Path("/tmp/repo"))
    assert s.llm_provider == "anthropic"
    assert s.repo_path == Path("/tmp/repo")


def test_settings_derived_paths(tmp_path: Path):
    cortex_dir = tmp_path / CORTEX_DIR_NAME
    s = Settings(cortex_dir=cortex_dir)
    assert s.notion_token_path == cortex_dir / "notion_tokens.json"
    assert s.faiss_index_dir == cortex_dir / "faiss_index"
    assert s.page_cache_path == cortex_dir / "page_cache.json"
    assert s.env_path == cortex_dir / ".env"
    assert s.data_dir == cortex_dir


def test_settings_is_initialized(tmp_path: Path):
    cortex_dir = tmp_path / CORTEX_DIR_NAME
    s = Settings(cortex_dir=cortex_dir)
    assert not s.is_initialized

    cortex_dir.mkdir()
    (cortex_dir / ".env").write_text("LLM_PROVIDER=google\n")
    assert s.is_initialized


def test_settings_from_env(tmp_path: Path):
    cortex_dir = tmp_path / CORTEX_DIR_NAME
    cortex_dir.mkdir()
    (cortex_dir / ".env").write_text("LLM_PROVIDER=anthropic\nANTHROPIC_API_KEY=test-key\n")

    s = Settings.from_env(tmp_path)
    assert s.llm_provider == "anthropic"
    assert s.anthropic_api_key == "test-key"
    assert s.repo_path == tmp_path


def test_settings_from_env_with_model(tmp_path: Path):
    cortex_dir = tmp_path / CORTEX_DIR_NAME
    cortex_dir.mkdir()
    (cortex_dir / ".env").write_text(
        "LLM_PROVIDER=google\nGOOGLE_API_KEY=key\nLLM_MODEL=gemini-3-flash-preview\n"
    )

    s = Settings.from_env(tmp_path)
    assert s.llm_model == "gemini-3-flash-preview"


def test_settings_from_env_default_model(tmp_path: Path):
    cortex_dir = tmp_path / CORTEX_DIR_NAME
    cortex_dir.mkdir()
    (cortex_dir / ".env").write_text("LLM_PROVIDER=google\nGOOGLE_API_KEY=key\n")

    s = Settings.from_env(tmp_path)
    assert s.llm_model == "gemini-2.5-flash-lite"


def test_settings_from_env_openrouter(tmp_path: Path):
    cortex_dir = tmp_path / CORTEX_DIR_NAME
    cortex_dir.mkdir()
    (cortex_dir / ".env").write_text(
        "LLM_PROVIDER=openrouter\nOPENROUTER_API_KEY=sk-or-test\n"
        "LLM_MODEL=anthropic/claude-sonnet-4\n"
    )

    s = Settings.from_env(tmp_path)
    assert s.llm_provider == "openrouter"
    assert s.openrouter_api_key == "sk-or-test"
    assert s.llm_model == "anthropic/claude-sonnet-4"
