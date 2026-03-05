"""Notion MCP client connection via Streamable HTTP."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from langchain_mcp_adapters.client import MultiServerMCPClient
from mcp.client.streamable_http import streamablehttp_client
from mcp import ClientSession

from codebase_cortex.auth.token_store import get_valid_token
from codebase_cortex.config import Settings
from codebase_cortex.utils.rate_limiter import NotionRateLimiter

NOTION_MCP_URL = "https://mcp.notion.com/mcp"

rate_limiter = NotionRateLimiter()


@asynccontextmanager
async def notion_mcp_session(settings: Settings) -> AsyncGenerator[ClientSession, None]:
    """Create a raw MCP client session to Notion.

    Handles token refresh and provides a connected session.
    """
    token = await get_valid_token(settings.notion_token_path)
    headers = {"Authorization": f"Bearer {token}"}

    async with streamablehttp_client(NOTION_MCP_URL, headers=headers) as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            yield session


async def get_notion_tools(settings: Settings) -> list:
    """Get LangChain-compatible tools from the Notion MCP server.

    Returns a list of tools that can be bound to LangChain agents.
    """
    token = await get_valid_token(settings.notion_token_path)

    client = MultiServerMCPClient(
        {
            "notion": {
                "url": NOTION_MCP_URL,
                "transport": "streamable_http",
                "headers": {"Authorization": f"Bearer {token}"},
            }
        }
    )
    async with client:
        return client.get_tools()
