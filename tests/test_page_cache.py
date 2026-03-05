"""Tests for page cache with fuzzy title matching."""

from __future__ import annotations

from pathlib import Path

from codebase_cortex.notion.page_cache import PageCache


def test_find_by_title_exact(tmp_path: Path):
    cache = PageCache(cache_path=tmp_path / "cache.json")
    cache.upsert("id1", "Architecture Overview")

    assert cache.find_by_title("Architecture Overview") is not None
    assert cache.find_by_title("Nonexistent") is None


def test_find_by_title_fuzzy_emoji(tmp_path: Path):
    cache = PageCache(cache_path=tmp_path / "cache.json")
    cache.upsert("id1", "\U0001f3d7\ufe0f Architecture Overview")

    # Exact match fails, fuzzy should work
    result = cache.find_by_title("Architecture Overview")
    assert result is not None
    assert result.page_id == "id1"


def test_find_by_title_fuzzy_case(tmp_path: Path):
    cache = PageCache(cache_path=tmp_path / "cache.json")
    cache.upsert("id1", "API Reference")

    result = cache.find_by_title("api reference")
    assert result is not None
    assert result.page_id == "id1"


def test_find_all_doc_pages(tmp_path: Path):
    cache = PageCache(cache_path=tmp_path / "cache.json")
    cache.upsert("parent", "Codebase Cortex")
    cache.upsert("id1", "Architecture Overview")
    cache.upsert("id2", "API Reference")

    doc_pages = cache.find_all_doc_pages()
    titles = [p.title for p in doc_pages]
    assert "Codebase Cortex" not in titles
    assert "Architecture Overview" in titles
    assert "API Reference" in titles


def test_normalize_title():
    norm = PageCache._normalize_title
    assert norm("\U0001f3d7\ufe0f Architecture Overview") == "architecture overview"
    assert norm("  API  Reference  ") == "api reference"
    assert norm("\u2705 Task Board") == "task board"
