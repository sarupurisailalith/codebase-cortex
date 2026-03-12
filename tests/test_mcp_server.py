"""Tests for the MCP server."""

from unittest.mock import patch, MagicMock
from codebase_cortex.mcp_server import create_server


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
        mock_settings.return_value = settings

        server = create_server()
        assert server.name == "cortex"
