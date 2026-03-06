"""Tests for bootstrap discovery functions."""

from __future__ import annotations

import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from codebase_cortex.notion.bootstrap import discover_child_pages, extract_page_id


def test_extract_page_id_from_result():
    result = MagicMock()
    result.isError = False
    result.content = [MagicMock(text="Created page https://notion.so/Page-31a142c2-294f-81f5-92b4-c6aacdc77598")]
    assert extract_page_id(result) == "31a142c2-294f-81f5-92b4-c6aacdc77598"


def test_extract_page_id_error():
    result = MagicMock()
    result.isError = True
    assert extract_page_id(result) is None


def test_extract_page_id_no_content():
    result = MagicMock()
    result.isError = False
    result.content = []
    assert extract_page_id(result) is None


@pytest.mark.asyncio
async def test_discover_child_pages_no_parent(tmp_path):
    """Discovery returns 0 when no parent page exists in cache."""
    from codebase_cortex.notion.page_cache import PageCache

    cache_path = tmp_path / "cache.json"
    cache = PageCache(cache_path=cache_path)
    # No parent page in cache

    settings = MagicMock()
    settings.page_cache_path = cache_path

    count = await discover_child_pages(settings)
    assert count == 0


@pytest.mark.asyncio
async def test_discover_child_pages_finds_new(tmp_path):
    """Discovery fetches and caches new child pages."""
    from codebase_cortex.notion.page_cache import PageCache

    cache_path = tmp_path / "cache.json"
    cache = PageCache(cache_path=cache_path)
    cache.upsert("parent-id-0000-0000-000000000001", "Codebase Cortex")

    settings = MagicMock()
    settings.page_cache_path = cache_path
    settings.notion_token_path = tmp_path / "tokens.json"

    # Mock the parent page response with a child page UUID in content
    child_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    parent_response = MagicMock()
    parent_response.isError = False
    parent_response.content = [
        MagicMock(
            text=(
                '<page url="https://notion.so/parent">\n'
                "<content>\n"
                f"[Setup Guide](https://notion.so/Setup-Guide-{child_id})\n"
                "</content>\n"
                "</page>"
            )
        )
    ]

    # Mock the child page fetch response
    child_response = MagicMock()
    child_response.isError = False
    child_response.content = [
        MagicMock(
            text=(
                '<page url="https://notion.so/child">\n'
                '<properties>{"title":"Setup Guide"}</properties>\n'
                "<content>Some docs</content>\n"
                "</page>"
            )
        )
    ]

    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(side_effect=[parent_response, child_response])
    mock_session.initialize = AsyncMock()

    with patch("codebase_cortex.mcp_client.notion_mcp_session") as mock_ctx:
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        count = await discover_child_pages(settings)

    assert count == 1
    # Reload cache and verify
    reloaded = PageCache(cache_path=cache_path)
    found = reloaded.find_by_title("Setup Guide")
    assert found is not None
    assert found.page_id == child_id


@pytest.mark.asyncio
async def test_discover_child_pages_skips_cached(tmp_path):
    """Discovery skips pages already in the cache."""
    from codebase_cortex.notion.page_cache import PageCache

    cache_path = tmp_path / "cache.json"
    cache = PageCache(cache_path=cache_path)
    cache.upsert("parent-id-0000-0000-000000000001", "Codebase Cortex")

    child_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    cache.upsert(child_id, "Already Cached Page")

    settings = MagicMock()
    settings.page_cache_path = cache_path
    settings.notion_token_path = tmp_path / "tokens.json"

    parent_response = MagicMock()
    parent_response.isError = False
    parent_response.content = [
        MagicMock(
            text=(
                "<content>\n"
                f"[Already Cached Page](https://notion.so/Page-{child_id})\n"
                "</content>"
            )
        )
    ]

    mock_session = AsyncMock()
    # Should only be called once (for parent fetch), not for the child
    mock_session.call_tool = AsyncMock(return_value=parent_response)
    mock_session.initialize = AsyncMock()

    with patch("codebase_cortex.mcp_client.notion_mcp_session") as mock_ctx:
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        count = await discover_child_pages(settings)

    assert count == 0
    # Only one call (parent fetch), no child fetches
    assert mock_session.call_tool.call_count == 1
