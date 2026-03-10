"""Tests for config module."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from codebase_cortex.config import Settings, CORTEX_DIR_NAME, get_model_for_node


ENV_KEYS = [
    "LLM_PROVIDER", "LLM_MODEL", "LLM_API_BASE", "LLM_API_KEY",
    "LLM_FALLBACK", "LLM_MODEL_CODE_ANALYZER", "LLM_MODEL_SECTION_ROUTER",
    "LLM_MODEL_DOC_WRITER", "LLM_MODEL_DOC_VALIDATOR",
    "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "GITHUB_TOKEN",
    "DOC_OUTPUT", "DOC_SYNC", "DOC_DETAIL_LEVEL", "DOC_STRATEGY",
    "DOC_OUTPUT_MODE", "DOC_SCOPE", "DOC_SCOPE_EXCLUDE",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Remove LLM-related env vars before each test to prevent leaking."""
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


# --- Settings defaults ---


def test_settings_defaults():
    s = Settings()
    assert s.llm_model == "gemini/gemini-2.5-flash-lite"
    assert s.llm_api_base is None
    assert s.llm_api_key is None
    assert s.llm_fallback is None
    assert s.doc_output == "local"
    assert s.doc_detail_level == "standard"
    assert s.doc_strategy == "main-only"
    assert s.doc_output_mode == "apply"
    assert s.oauth_callback_port == 9876


def test_settings_custom():
    s = Settings(llm_model="anthropic/claude-sonnet-4-20250514", repo_path=Path("/tmp/repo"))
    assert s.llm_model == "anthropic/claude-sonnet-4-20250514"
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
    (cortex_dir / ".env").write_text("LLM_MODEL=google/gemini-2.5-flash-lite\n")
    assert s.is_initialized


# --- from_env: v0.2 format ---


def test_settings_from_env_v2_format(tmp_path: Path):
    cortex_dir = tmp_path / CORTEX_DIR_NAME
    cortex_dir.mkdir()
    (cortex_dir / ".env").write_text(
        "LLM_MODEL=anthropic/claude-sonnet-4-20250514\n"
        "DOC_OUTPUT=notion\n"
        "DOC_DETAIL_LEVEL=detailed\n"
    )

    s = Settings.from_env(tmp_path)
    assert s.llm_model == "anthropic/claude-sonnet-4-20250514"
    assert s.doc_output == "notion"
    assert s.doc_detail_level == "detailed"
    assert s.repo_path == tmp_path


def test_settings_from_env_per_node_overrides(tmp_path: Path):
    cortex_dir = tmp_path / CORTEX_DIR_NAME
    cortex_dir.mkdir()
    (cortex_dir / ".env").write_text(
        "LLM_MODEL=google/gemini-2.5-flash-lite\n"
        "LLM_MODEL_DOC_WRITER=anthropic/claude-sonnet-4-20250514\n"
    )

    s = Settings.from_env(tmp_path)
    assert s.llm_model == "google/gemini-2.5-flash-lite"
    assert s.llm_model_doc_writer == "anthropic/claude-sonnet-4-20250514"
    assert s.llm_model_code_analyzer is None


# --- from_env: v0.1 migration ---


def test_settings_from_env_v1_migration(tmp_path: Path):
    """v0.1 format (LLM_PROVIDER + LLM_MODEL) is auto-migrated to v0.2."""
    cortex_dir = tmp_path / CORTEX_DIR_NAME
    cortex_dir.mkdir()
    (cortex_dir / ".env").write_text(
        "LLM_PROVIDER=google\nLLM_MODEL=gemini-2.5-flash-lite\nGOOGLE_API_KEY=test-key\n"
    )

    s = Settings.from_env(tmp_path)
    # Should be migrated to provider/model format
    assert s.llm_model == "google/gemini-2.5-flash-lite"
    assert s.google_api_key == "test-key"

    # .env should be backed up
    assert (cortex_dir / ".env.bak").exists()

    # .env should be updated (LLM_PROVIDER removed, LLM_MODEL updated)
    content = (cortex_dir / ".env").read_text()
    assert "LLM_PROVIDER" not in content
    assert "LLM_MODEL=google/gemini-2.5-flash-lite" in content


def test_settings_from_env_v1_anthropic_migration(tmp_path: Path):
    cortex_dir = tmp_path / CORTEX_DIR_NAME
    cortex_dir.mkdir()
    (cortex_dir / ".env").write_text(
        "LLM_PROVIDER=anthropic\nANTHROPIC_API_KEY=test-key\n"
    )

    s = Settings.from_env(tmp_path)
    # Default model for anthropic provider
    assert s.llm_model == "anthropic/claude-sonnet-4-20250514"


def test_settings_from_env_v1_openrouter_migration(tmp_path: Path):
    cortex_dir = tmp_path / CORTEX_DIR_NAME
    cortex_dir.mkdir()
    (cortex_dir / ".env").write_text(
        "LLM_PROVIDER=openrouter\nOPENROUTER_API_KEY=sk-or-test\n"
        "LLM_MODEL=anthropic/claude-sonnet-4\n"
    )

    s = Settings.from_env(tmp_path)
    # OpenRouter model already has / so should be treated as v0.2 format
    assert s.llm_model == "anthropic/claude-sonnet-4"


# --- get_model_for_node ---


def test_get_model_for_node_default():
    s = Settings(llm_model="google/gemini-2.5-flash-lite")
    assert get_model_for_node(s, "code_analyzer") == "google/gemini-2.5-flash-lite"


def test_get_model_for_node_override():
    s = Settings(
        llm_model="google/gemini-2.5-flash-lite",
        llm_model_doc_writer="anthropic/claude-sonnet-4-20250514",
    )
    assert get_model_for_node(s, "doc_writer") == "anthropic/claude-sonnet-4-20250514"
    assert get_model_for_node(s, "code_analyzer") == "google/gemini-2.5-flash-lite"


def test_get_model_for_node_empty_name():
    s = Settings(llm_model="google/gemini-2.5-flash-lite")
    assert get_model_for_node(s, "") == "google/gemini-2.5-flash-lite"


# --- Doc config defaults ---


def test_settings_doc_defaults(tmp_path: Path):
    cortex_dir = tmp_path / CORTEX_DIR_NAME
    cortex_dir.mkdir()
    (cortex_dir / ".env").write_text("LLM_MODEL=google/gemini-2.5-flash-lite\n")

    s = Settings.from_env(tmp_path)
    assert s.doc_output == "local"
    assert s.doc_sync is None
    assert s.doc_detail_level == "standard"
    assert s.doc_strategy == "main-only"
    assert s.doc_output_mode == "apply"
    assert s.doc_scope is None
    assert s.doc_scope_exclude is None
