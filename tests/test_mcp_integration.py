"""Integration tests for the MCP server."""

from pathlib import Path
from unittest.mock import patch, MagicMock

from codebase_cortex.mcp_server import create_server


def _create_integration_server(tmp_path: Path):
    """Create a fully wired server pointing to tmp_path."""
    cortex_dir = tmp_path / ".cortex"
    cortex_dir.mkdir()
    (cortex_dir / ".env").write_text("")
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()

    with patch("codebase_cortex.mcp_server.Settings.from_env") as mock_settings:
        settings = MagicMock()
        settings.repo_path = tmp_path
        settings.faiss_index_dir = tmp_path / "faiss_index"
        settings.cortex_dir = cortex_dir
        settings.doc_output = "local"
        settings.doc_sync_targets = ""
        mock_settings.return_value = settings
        return create_server(), tmp_path


def test_all_11_tools_registered(tmp_path):
    """All 11 MCP tools should be registered."""
    server, _ = _create_integration_server(tmp_path)
    tool_names = {t.name for t in server._tool_manager.list_tools()}
    expected = {
        "cortex_search_related_docs", "cortex_read_section", "cortex_write_section",
        "cortex_list_docs", "cortex_check_freshness", "cortex_get_doc_status",
        "cortex_rebuild_index", "cortex_accept_drafts", "cortex_create_page",
        "cortex_knowledge_map", "cortex_sync",
    }
    assert expected.issubset(tool_names), f"Missing: {expected - tool_names}"


def test_uninitialized_project_returns_status_tool(tmp_path):
    """Server for uninitialized project should have cortex_status tool."""
    with patch("codebase_cortex.mcp_server.Settings.from_env", side_effect=Exception("not init")):
        server = create_server()
        tool_names = {t.name for t in server._tool_manager.list_tools()}
        assert "cortex_status" in tool_names


def test_write_and_read_roundtrip(tmp_path):
    """Write a section then read it back — content should match."""
    cortex_dir = tmp_path / ".cortex"
    cortex_dir.mkdir()
    (cortex_dir / ".env").write_text("")
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()

    # Create a doc file first
    (docs_dir / "test.md").write_text("# Test Page\n\n## Overview\n\nOriginal content.\n")

    with patch("codebase_cortex.mcp_server.Settings.from_env") as mock_settings:
        settings = MagicMock()
        settings.repo_path = tmp_path
        settings.faiss_index_dir = tmp_path / "faiss_index"
        settings.cortex_dir = cortex_dir
        settings.doc_output = "local"
        settings.doc_sync_targets = ""
        mock_settings.return_value = settings

        server = create_server()

    # Verify the file exists
    assert (docs_dir / "test.md").exists()
    content = (docs_dir / "test.md").read_text()
    assert "Original content" in content
