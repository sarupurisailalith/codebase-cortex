"""Tests for config module."""

from __future__ import annotations

from pathlib import Path

from codebase_cortex.config import Settings, CORTEX_DIR_NAME


def test_settings_defaults():
    s = Settings()
    assert s.llm_provider == "google"
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
