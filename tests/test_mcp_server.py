"""Tests for the MCP server."""

from unittest.mock import patch, MagicMock
from codebase_cortex.mcp_server import create_server


def _create_test_server(tmp_path):
    """Create a server with mocked settings pointing to tmp_path."""
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

        server = create_server()
        return server, docs_dir, settings


def test_create_server_returns_fastmcp_instance(tmp_path):
    """Server should create successfully with a valid .cortex setup."""
    cortex_dir = tmp_path / ".cortex"
    cortex_dir.mkdir()
    (cortex_dir / ".env").write_text("LLM_MODEL=gemini/gemini-2.5-flash-lite\n")
    faiss_dir = cortex_dir / "faiss_index"
    faiss_dir.mkdir()
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()

    with patch("codebase_cortex.mcp_server.Settings.from_env") as mock_settings:
        settings = MagicMock()
        settings.repo_path = tmp_path
        settings.faiss_index_dir = faiss_dir
        settings.cortex_dir = cortex_dir
        settings.doc_output = "local"
        settings.doc_sync_targets = ""
        mock_settings.return_value = settings

        server = create_server()
        assert server.name == "cortex"


def test_all_core_tools_registered(tmp_path):
    """All 6 core MCP tools should be registered on the server."""
    server, _, _ = _create_test_server(tmp_path)
    tool_names = {t.name for t in server._tool_manager.list_tools()}
    expected = {
        "cortex_search_related_docs",
        "cortex_read_section",
        "cortex_write_section",
        "cortex_list_docs",
        "cortex_check_freshness",
        "cortex_get_doc_status",
    }
    assert expected.issubset(tool_names), f"Missing tools: {expected - tool_names}"


def test_cortex_search_related_docs_registered(tmp_path):
    """cortex_search_related_docs tool should be registered."""
    server, _, _ = _create_test_server(tmp_path)
    tool_names = {t.name for t in server._tool_manager.list_tools()}
    assert "cortex_search_related_docs" in tool_names


def test_cortex_read_section_registered(tmp_path):
    """cortex_read_section tool should be registered."""
    server, _, _ = _create_test_server(tmp_path)
    tool_names = {t.name for t in server._tool_manager.list_tools()}
    assert "cortex_read_section" in tool_names


def test_cortex_write_section_registered(tmp_path):
    """cortex_write_section tool should be registered."""
    server, _, _ = _create_test_server(tmp_path)
    tool_names = {t.name for t in server._tool_manager.list_tools()}
    assert "cortex_write_section" in tool_names


def test_cortex_list_docs_registered(tmp_path):
    """cortex_list_docs tool should be registered."""
    server, _, _ = _create_test_server(tmp_path)
    tool_names = {t.name for t in server._tool_manager.list_tools()}
    assert "cortex_list_docs" in tool_names


def test_cortex_check_freshness_registered(tmp_path):
    """cortex_check_freshness tool should be registered."""
    server, _, _ = _create_test_server(tmp_path)
    tool_names = {t.name for t in server._tool_manager.list_tools()}
    assert "cortex_check_freshness" in tool_names


def test_cortex_get_doc_status_registered(tmp_path):
    """cortex_get_doc_status tool should be registered."""
    server, _, _ = _create_test_server(tmp_path)
    tool_names = {t.name for t in server._tool_manager.list_tools()}
    assert "cortex_get_doc_status" in tool_names


def test_write_section_creates_file(tmp_path):
    """cortex_write_section should create a new doc file when it doesn't exist."""
    server, docs_dir, settings = _create_test_server(tmp_path)

    # Find and call the write_section tool function directly
    tool_fn = None
    for t in server._tool_manager.list_tools():
        if t.name == "cortex_write_section":
            tool_fn = t.fn
            break

    assert tool_fn is not None, "cortex_write_section tool not found"

    result = tool_fn(doc_file="test-page.md", heading="## Overview", content="This is a test page.")
    assert result["status"] == "created"
    assert result["doc_file"] == "test-page.md"

    created_file = docs_dir / "test-page.md"
    assert created_file.exists()
    content = created_file.read_text()
    assert "Overview" in content or "test" in content
