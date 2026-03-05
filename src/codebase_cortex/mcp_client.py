"""Notion MCP client connection via Streamable HTTP."""

from __future__ import annotations

import json
import logging
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


class LoggingSession:
    """Wrapper around ClientSession that logs all tool calls."""

    def __init__(self, session: ClientSession):
        self._session = session
        self._logger = logging.getLogger("cortex")

    async def call_tool(self, name: str, arguments: dict | None = None):
        args_str = json.dumps(arguments, default=str)[:500] if arguments else "{}"
        self._logger.debug(f"MCP CALL: {name}({args_str})")

        result = await self._session.call_tool(name, arguments=arguments)

        if result.isError:
            self._logger.debug(f"MCP ERROR: {name} -> {result.content}")
        else:
            preview = ""
            if result.content:
                preview = result.content[0].text[:300]
            self._logger.debug(f"MCP OK: {name} -> {preview}...")

        return result

    async def list_tools(self):
        return await self._session.list_tools()

    async def initialize(self):
        return await self._session.initialize()


@asynccontextmanager
async def notion_mcp_session(settings: Settings) -> AsyncGenerator[ClientSession, None]:
    """Create a raw MCP client session to Notion.

    Handles token refresh and provides a connected session.
    Wraps in LoggingSession when verbose mode is active.
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
            from codebase_cortex.utils.logging import is_verbose
            if is_verbose():
                yield LoggingSession(session)
            else:
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
