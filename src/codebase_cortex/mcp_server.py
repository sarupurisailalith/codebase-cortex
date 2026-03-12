"""MCP server exposing Cortex documentation tools to coding agents.

All tools are deterministic — no LLM required. The coding agent's own LLM
does the reasoning; Cortex provides semantic search, section tracking,
metadata, and file management.

Start with: cortex mcp serve
"""

from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP

from codebase_cortex.config import Settings
from codebase_cortex.embeddings.store import FAISSStore
from codebase_cortex.backends.meta_index import MetaIndex

logger = logging.getLogger("cortex")


def create_server() -> FastMCP:
    """Create and configure the Cortex MCP server with all tools."""
    mcp = FastMCP("cortex", instructions="Documentation intelligence for your codebase")

    # Load project configuration and indexes at startup
    settings = Settings.from_env()
    store = FAISSStore(settings.faiss_index_dir)
    store.load()
    docs_dir = settings.repo_path / "docs"
    meta = MetaIndex(docs_dir)
    meta.load()

    # Tools will be registered in subsequent tasks

    return mcp
