"""Tests for DocBackend protocol, LocalMarkdownBackend, MetaIndex, and backend factory."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from codebase_cortex.backends import get_backend
from codebase_cortex.backends.local_markdown import LocalMarkdownBackend
from codebase_cortex.backends.meta_index import MetaIndex
from codebase_cortex.backends.protocol import DocBackend


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def docs_dir(tmp_path: Path) -> Path:
    d = tmp_path / "docs"
    d.mkdir()
    return d


@pytest.fixture
def meta(docs_dir: Path) -> MetaIndex:
    return MetaIndex(docs_dir)


def _make_settings(tmp_path: Path, doc_output: str = "local"):
    """Create a minimal Settings pointing at tmp_path as the repo root."""
    from codebase_cortex.config import Settings

    cortex_dir = tmp_path / ".cortex"
    cortex_dir.mkdir(exist_ok=True)
    return Settings(repo_path=tmp_path, cortex_dir=cortex_dir, doc_output=doc_output)


@pytest.fixture
def settings(tmp_path: Path):
    return _make_settings(tmp_path)


@pytest.fixture
def backend(settings) -> LocalMarkdownBackend:
    return LocalMarkdownBackend(settings)


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_local_backend_implements_protocol(tmp_path: Path):
    """LocalMarkdownBackend should satisfy the DocBackend protocol."""
    assert isinstance(LocalMarkdownBackend, type)
    # runtime_checkable protocol — create a dummy to verify
    s = _make_settings(tmp_path)
    b = LocalMarkdownBackend(s)
    assert isinstance(b, DocBackend)


# ---------------------------------------------------------------------------
# Backend factory
# ---------------------------------------------------------------------------


def test_get_backend_local(tmp_path: Path):
    s = _make_settings(tmp_path, doc_output="local")
    b = get_backend(s)
    assert isinstance(b, LocalMarkdownBackend)


def test_get_backend_notion(tmp_path: Path):
    from codebase_cortex.backends.notion_backend import NotionBackend

    s = _make_settings(tmp_path, doc_output="notion")
    b = get_backend(s)
    assert isinstance(b, NotionBackend)


def test_get_backend_unknown_raises(tmp_path: Path):
    s = _make_settings(tmp_path, doc_output="confluence")
    with pytest.raises(ValueError, match="Unknown doc_output"):
        get_backend(s)


# ---------------------------------------------------------------------------
# MetaIndex
# ---------------------------------------------------------------------------


class TestMetaIndex:
    def test_empty_meta(self, meta: MetaIndex):
        data = meta.load()
        assert data["version"] == 2
        assert data["pages"] == {}

    def test_save_and_load(self, meta: MetaIndex):
        meta.load()
        meta.set_page("arch.md", "Architecture")
        meta.save()

        # Create a fresh instance and load from disk
        meta2 = MetaIndex(meta.docs_dir)
        data = meta2.load()
        assert "arch.md" in data["pages"]
        assert data["pages"]["arch.md"]["title"] == "Architecture"

    def test_set_page_creates_entry(self, meta: MetaIndex):
        meta.load()
        page = meta.set_page("api.md", "API Reference")
        assert page["title"] == "API Reference"
        assert page["sections"] == []

    def test_set_page_updates_existing(self, meta: MetaIndex):
        meta.load()
        meta.set_page("api.md", "API Reference")
        meta.set_page("api.md", "API Ref v2")
        assert meta.data["pages"]["api.md"]["title"] == "API Ref v2"

    def test_update_section(self, meta: MetaIndex):
        meta.load()
        meta.set_page("arch.md", "Architecture")
        meta.update_section(
            page="arch.md",
            heading="## Overview",
            content_hash="abc123",
            cortex_hash="abc123",
            line_range=(1, 10),
        )
        sections = meta.get_section_tree("arch.md")
        assert len(sections) == 1
        assert sections[0]["heading"] == "## Overview"
        assert sections[0]["content_hash"] == "abc123"
        assert sections[0]["line_range"] == [1, 10]

    def test_update_section_overwrites(self, meta: MetaIndex):
        meta.load()
        meta.set_page("arch.md", "Architecture")
        meta.update_section("arch.md", "## Overview", "hash1", "hash1", (1, 10))
        meta.update_section("arch.md", "## Overview", "hash2", "hash1", (1, 12))
        sections = meta.get_section_tree("arch.md")
        assert len(sections) == 1
        assert sections[0]["content_hash"] == "hash2"
        assert sections[0]["line_range"] == [1, 12]

    def test_get_section_hashes(self, meta: MetaIndex):
        meta.load()
        meta.set_page("arch.md", "Architecture")
        meta.update_section("arch.md", "## Overview", "aaa", "bbb", (1, 5))
        content_hash, cortex_hash = meta.get_section_hashes("arch.md", "## Overview")
        assert content_hash == "aaa"
        assert cortex_hash == "bbb"

    def test_get_section_hashes_missing(self, meta: MetaIndex):
        meta.load()
        h, c = meta.get_section_hashes("nope.md", "## Nothing")
        assert h == ""
        assert c == ""

    def test_is_human_edited(self, meta: MetaIndex):
        meta.load()
        meta.set_page("arch.md", "Architecture")
        # Both hashes equal → not edited
        meta.update_section("arch.md", "## Overview", "same", "same", (1, 5))
        assert not meta.is_human_edited("arch.md", "## Overview")

        # Hashes differ → human edited
        meta.update_section("arch.md", "## Overview", "new", "old", (1, 5))
        assert meta.is_human_edited("arch.md", "## Overview")

    def test_is_human_edited_empty_hashes(self, meta: MetaIndex):
        meta.load()
        # No page at all → not edited
        assert not meta.is_human_edited("nope.md", "## X")

    def test_update_run_metrics(self, meta: MetaIndex):
        meta.load()
        meta.update_run_metrics({"sections_updated": 5, "cost": 0.01})
        assert meta.data["last_run"]["sections_updated"] == 5
        assert "timestamp" in meta.data["last_run"]

    def test_initialize_from_files(self, docs_dir: Path):
        # Write a sample markdown file
        (docs_dir / "arch.md").write_text(
            "# Architecture\n\nOverview text.\n\n## Components\n\nComponent details.\n"
        )
        meta = MetaIndex(docs_dir)
        meta.load()
        meta.initialize_from_files()

        assert "arch.md" in meta.data["pages"]
        page = meta.data["pages"]["arch.md"]
        assert page["title"] == "Architecture"
        assert len(page["sections"]) == 2  # # Architecture, ## Components

    def test_compute_content_hashes(self, docs_dir: Path):
        # Set up a file and meta with a stale hash
        (docs_dir / "api.md").write_text("# API\n\nEndpoint info.\n")
        meta = MetaIndex(docs_dir)
        meta.load()
        meta.set_page("api.md", "API")
        meta.update_section("api.md", "# API", "stale_hash", "stale_hash", (1, 3))
        meta.save()

        meta.compute_content_hashes()
        sections = meta.get_section_tree("api.md")
        assert sections[0]["content_hash"] != "stale_hash"
        assert sections[0]["content_hash"]  # Not empty


# ---------------------------------------------------------------------------
# LocalMarkdownBackend
# ---------------------------------------------------------------------------


class TestLocalMarkdownBackend:
    @pytest.mark.asyncio
    async def test_write_page_creates_file(self, backend: LocalMarkdownBackend):
        ref = await backend.write_page("", "My Page", "# My Page\n\nContent.", "create")
        assert ref == "my-page.md"
        assert (backend.docs_dir / "my-page.md").exists()

    @pytest.mark.asyncio
    async def test_write_page_with_ref(self, backend: LocalMarkdownBackend):
        ref = await backend.write_page("arch.md", "Architecture", "# Arch\n\nText.", "create")
        assert ref == "arch.md"
        content = (backend.docs_dir / "arch.md").read_text()
        assert "# Arch" in content

    @pytest.mark.asyncio
    async def test_write_page_updates_meta(self, backend: LocalMarkdownBackend):
        await backend.write_page("arch.md", "Architecture", "# Architecture\n\nOverview.", "create")
        page = backend.meta.get_page("arch.md")
        assert page is not None
        assert page["title"] == "Architecture"

    @pytest.mark.asyncio
    async def test_fetch_page_list_empty(self, backend: LocalMarkdownBackend):
        pages = await backend.fetch_page_list()
        assert pages == []

    @pytest.mark.asyncio
    async def test_fetch_page_list_after_write(self, backend: LocalMarkdownBackend):
        await backend.write_page("arch.md", "Architecture", "# Architecture\n\nText.", "create")
        pages = await backend.fetch_page_list()
        assert len(pages) == 1
        assert pages[0]["ref"] == "arch.md"
        assert pages[0]["title"] == "Architecture"

    @pytest.mark.asyncio
    async def test_fetch_section_by_heading(self, backend: LocalMarkdownBackend):
        content = "# Title\n\nPreamble.\n\n## Overview\n\nOverview content.\n\n## API\n\nAPI content."
        await backend.write_page("doc.md", "Doc", content, "create")

        section = await backend.fetch_section("doc.md", "## Overview")
        assert "Overview content" in section

    @pytest.mark.asyncio
    async def test_fetch_section_by_line_range(self, backend: LocalMarkdownBackend):
        content = "# Title\n\nPreamble.\n\n## Overview\n\nOverview content.\n\n## API\n\nAPI content."
        (backend.docs_dir / "doc.md").write_text(content)

        # Lines 5-7: "## Overview\n\nOverview content."
        section = await backend.fetch_section("doc.md", "## Overview", line_range=(5, 7))
        assert "Overview content" in section

    @pytest.mark.asyncio
    async def test_fetch_section_missing_file(self, backend: LocalMarkdownBackend):
        result = await backend.fetch_section("nonexistent.md", "## Nope")
        assert result == ""

    @pytest.mark.asyncio
    async def test_fetch_section_heading_not_found(self, backend: LocalMarkdownBackend):
        (backend.docs_dir / "doc.md").write_text("# Title\n\nJust content.")
        result = await backend.fetch_section("doc.md", "## Missing")
        assert result == ""

    @pytest.mark.asyncio
    async def test_write_section_new_file(self, backend: LocalMarkdownBackend):
        await backend.write_section("new.md", "## Overview", "Some overview text.")
        assert (backend.docs_dir / "new.md").exists()
        content = (backend.docs_dir / "new.md").read_text()
        assert "## Overview" in content

    @pytest.mark.asyncio
    async def test_write_section_merge_existing(self, backend: LocalMarkdownBackend):
        initial = "# Doc\n\nIntro.\n\n## Overview\n\nOld overview.\n\n## API\n\nAPI stuff."
        await backend.write_page("doc.md", "Doc", initial, "create")

        await backend.write_section("doc.md", "## Overview", "New overview text.")
        content = (backend.docs_dir / "doc.md").read_text()
        assert "New overview text" in content
        assert "API stuff" in content  # Other sections preserved
        assert "Old overview" not in content  # Replaced

    @pytest.mark.asyncio
    async def test_create_task(self, backend: LocalMarkdownBackend):
        await backend.create_task({"title": "Document auth", "priority": "high", "description": "Auth flow needs docs."})
        task_file = backend.docs_dir / "task-board.md"
        assert task_file.exists()
        content = task_file.read_text()
        assert "Document auth" in content
        assert "🔴" in content
        assert "high" in content

    @pytest.mark.asyncio
    async def test_create_task_appends(self, backend: LocalMarkdownBackend):
        await backend.create_task({"title": "Task 1", "priority": "high"})
        await backend.create_task({"title": "Task 2", "priority": "low"})
        content = (backend.docs_dir / "task-board.md").read_text()
        assert "Task 1" in content
        assert "Task 2" in content
        assert "🔴" in content
        assert "🟢" in content

    @pytest.mark.asyncio
    async def test_create_task_updates_meta(self, backend: LocalMarkdownBackend):
        await backend.create_task({"title": "T1", "priority": "high"})
        await backend.create_task({"title": "T2", "priority": "medium"})
        tasks_meta = backend.meta.data["tasks"]
        assert tasks_meta["total"] == 2
        assert tasks_meta["by_priority"]["high"] == 1
        assert tasks_meta["by_priority"]["medium"] == 1

    @pytest.mark.asyncio
    async def test_append_to_log(self, backend: LocalMarkdownBackend):
        await backend.append_to_log("", "Sprint summary content.")
        log = backend.docs_dir / "sprint-log.md"
        assert log.exists()
        content = log.read_text()
        assert "Sprint Log" in content
        assert "Sprint summary content." in content

    @pytest.mark.asyncio
    async def test_append_to_log_appends(self, backend: LocalMarkdownBackend):
        await backend.append_to_log("", "Entry 1")
        await backend.append_to_log("", "Entry 2")
        content = (backend.docs_dir / "sprint-log.md").read_text()
        assert "Entry 1" in content
        assert "Entry 2" in content

    @pytest.mark.asyncio
    async def test_append_to_log_updates_meta(self, backend: LocalMarkdownBackend):
        await backend.append_to_log("", "Entry")
        sprint_meta = backend.meta.data["sprint_log"]
        assert sprint_meta["total_entries"] == 1
        assert sprint_meta["latest_entry"] is not None

    @pytest.mark.asyncio
    async def test_search_pages_finds_by_content(self, backend: LocalMarkdownBackend):
        (backend.docs_dir / "auth.md").write_text("# Authentication\n\nOAuth2 flow details.")
        (backend.docs_dir / "api.md").write_text("# API\n\nREST endpoints.")
        results = await backend.search_pages("OAuth")
        assert len(results) == 1
        assert results[0]["ref"] == "auth.md"

    @pytest.mark.asyncio
    async def test_search_pages_finds_by_filename(self, backend: LocalMarkdownBackend):
        (backend.docs_dir / "auth-flow.md").write_text("# Auth Flow\n\nDetails.")
        results = await backend.search_pages("auth")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_search_pages_no_results(self, backend: LocalMarkdownBackend):
        (backend.docs_dir / "api.md").write_text("# API\n\nContent.")
        results = await backend.search_pages("zebra")
        assert results == []

    @pytest.mark.asyncio
    async def test_slugify(self, backend: LocalMarkdownBackend):
        assert backend._slugify("My Cool Page!") == "my-cool-page"
        assert backend._slugify("  Spaces  Everywhere  ") == "spaces-everywhere"
        assert backend._slugify("") == "untitled"
        assert backend._slugify("API Reference (v2)") == "api-reference-v2"

    @pytest.mark.asyncio
    async def test_dual_hash_tracking(self, backend: LocalMarkdownBackend):
        """Verify write_page sets cortex_hash equal to content_hash."""
        content = "# Arch\n\nOverview text."
        await backend.write_page("arch.md", "Architecture", content, "create")

        sections = backend.meta.get_section_tree("arch.md")
        for sec in sections:
            assert sec["content_hash"] == sec["cortex_hash"]
            assert sec["content_hash"] != ""


# ---------------------------------------------------------------------------
# NotionBackend helpers
# ---------------------------------------------------------------------------


class TestNotionHelpers:
    def test_unescape_notion_text(self):
        from codebase_cortex.backends.notion_backend import _unescape_notion_text

        assert _unescape_notion_text("hello\\nworld") == "hello\nworld"
        assert _unescape_notion_text("tab\\there") == "tab\there"
        assert _unescape_notion_text("no escapes") == "no escapes"

    def test_strip_notion_metadata_content_tags(self):
        from codebase_cortex.backends.notion_backend import strip_notion_metadata

        raw = (
            'Here is the result of "view" for the Page...\n'
            "<page>\n"
            "<properties>{}</properties>\n"
            "<content>\n"
            "# Real Content\\n\\nSome text.\n"
            "</content>\n"
            "</page>"
        )
        result = strip_notion_metadata(raw)
        assert "Real Content" in result
        assert "<page>" not in result

    def test_strip_notion_metadata_fallback(self):
        from codebase_cortex.backends.notion_backend import strip_notion_metadata

        raw = '<page url="x"><properties>{"title":"Test"}</properties>Just some content</page>'
        result = strip_notion_metadata(raw)
        assert "Just some content" in result
        assert "<page" not in result
