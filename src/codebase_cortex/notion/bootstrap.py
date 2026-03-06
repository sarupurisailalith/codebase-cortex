"""Bootstrap starter Notion pages via MCP on first run."""

from __future__ import annotations

from mcp import ClientSession

from codebase_cortex.config import Settings
from codebase_cortex.notion.page_cache import PageCache
from codebase_cortex.utils.logging import get_logger

logger = get_logger()

PARENT_PAGE_TITLE = "Codebase Cortex"


def normalize_page_id(raw_id: str) -> str:
    """Normalize a Notion page ID to dashed UUID format.

    Notion URLs use dashless IDs, but our cache stores dashed format.
    This ensures consistent lookups.
    """
    clean = raw_id.replace("-", "").lower()
    if len(clean) == 32:
        return f"{clean[:8]}-{clean[8:12]}-{clean[12:16]}-{clean[16:20]}-{clean[20:]}"
    return raw_id

STARTER_PAGES = [
    {
        "title": "Architecture Overview",
        "icon": "🏗️",
        "description": "System design, component relationships, and architectural decisions.",
    },
    {
        "title": "API Reference",
        "icon": "📡",
        "description": "Endpoints, schemas, contracts, and integration points.",
    },
    {
        "title": "Sprint Log",
        "icon": "📋",
        "description": "Weekly auto-generated summaries of code changes and documentation updates.",
    },
    {
        "title": "Task Board",
        "icon": "✅",
        "description": "Undocumented areas, documentation debt, and improvement tasks.",
    },
]


def extract_page_id(result) -> str | None:
    """Extract a page ID from an MCP CallToolResult.

    The response text typically contains markdown with page URLs.
    We look for a UUID pattern which is the page ID.
    """
    import re

    if result.isError:
        return None

    if not result.content:
        return None

    text = result.content[0].text

    # Look for UUID pattern (with or without dashes)
    uuid_pattern = r"[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}"
    match = re.search(uuid_pattern, text, re.IGNORECASE)
    if match:
        return normalize_page_id(match.group(0))

    return text


async def search_page_by_title(session: ClientSession, title: str) -> str | None:
    """Search Notion for a page by title, return page_id if found."""
    from codebase_cortex.utils.rate_limiter import NotionRateLimiter

    rate_limiter = NotionRateLimiter()
    await rate_limiter.acquire()

    try:
        result = await session.call_tool(
            "notion-search",
            arguments={"query": title},
        )
        if result.isError or not result.content:
            return None

        # The search result text contains page info with IDs
        import re
        text = result.content[0].text

        # Look for the title in results and extract its page ID
        # Notion search returns markdown with page URLs/IDs
        uuid_pattern = r"[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}"
        match = re.search(uuid_pattern, text, re.IGNORECASE)
        if match and title.lower() in text.lower():
            return normalize_page_id(match.group(0))

        return None
    except Exception:
        return None


async def discover_child_pages(settings: Settings) -> int:
    """Discover child pages under the parent Notion page and cache them.

    Fetches the parent page via MCP, extracts child page references
    from the content, and caches any pages not already tracked.

    Returns the number of newly discovered pages.
    """
    import re
    from codebase_cortex.mcp_client import notion_mcp_session
    from codebase_cortex.utils.rate_limiter import NotionRateLimiter
    from codebase_cortex.notion.page_cache import PageCache

    logger = get_logger()
    cache = PageCache(cache_path=settings.page_cache_path)
    parent_page = cache.find_by_title("Codebase Cortex")
    if not parent_page:
        return 0

    rate_limiter = NotionRateLimiter()
    discovered = 0

    try:
        async with notion_mcp_session(settings) as session:
            await rate_limiter.acquire()
            result = await session.call_tool(
                "notion-fetch",
                arguments={"id": parent_page.page_id},
            )

            if result.isError or not result.content:
                return 0

            response_text = result.content[0].text

            # Extract content section (child pages are referenced there)
            content_match = re.search(
                r"<content>\s*(.*?)\s*</content>",
                response_text,
                re.DOTALL,
            )
            content = content_match.group(1) if content_match else response_text

            # Find all UUID patterns in the content (child page references)
            uuid_pattern = r"[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}"
            raw_ids = re.findall(uuid_pattern, content, re.IGNORECASE)
            found_ids = {normalize_page_id(pid) for pid in raw_ids}

            # Remove parent's own ID
            found_ids.discard(parent_page.page_id)

            # Filter to only truly new pages (not already cached)
            new_ids = [pid for pid in found_ids if not cache.get(pid)]

            for page_id in new_ids:
                await rate_limiter.acquire()
                try:
                    fetch_result = await session.call_tool(
                        "notion-fetch",
                        arguments={"id": page_id},
                    )
                    if not fetch_result.isError and fetch_result.content:
                        page_text = fetch_result.content[0].text
                        title_match = re.search(
                            r'"title"\s*:\s*"([^"]+)"', page_text
                        )
                        if title_match:
                            title = title_match.group(1)
                            cache.upsert(page_id, title)
                            discovered += 1
                            logger.info(f"Discovered child page: {title}")
                except Exception:
                    pass

    except Exception as e:
        logger.warning(f"Child page discovery failed: {e}")

    return discovered


async def bootstrap_notion_pages(settings: Settings) -> list[dict]:
    """Create the starter Notion pages via MCP tools.

    Creates a parent "Codebase Cortex" page, then child pages under it.
    Searches for existing pages first to avoid duplicates.
    Seeds the page cache with all created/found pages.

    Args:
        settings: Application settings with Notion token path.

    Returns:
        List of page info dicts with page_id and title.
    """
    from codebase_cortex.mcp_client import notion_mcp_session
    from codebase_cortex.utils.rate_limiter import NotionRateLimiter

    rate_limiter = NotionRateLimiter()
    cache = PageCache(cache_path=settings.page_cache_path)
    pages = []

    repo_name = settings.repo_path.name
    parent_title = repo_name

    async with notion_mcp_session(settings) as session:
        # Step 1: Search for existing parent page
        parent_id = await search_page_by_title(session, PARENT_PAGE_TITLE)

        # Step 2: Create parent page if not found
        if not parent_id:
            await rate_limiter.acquire()
            try:
                result = await session.call_tool(
                    "notion-create-pages",
                    arguments={
                        "pages": [
                            {
                                "properties": {"title": parent_title},
                                "content": (
                                    f"# {repo_name}\n\n"
                                    f"Auto-generated documentation hub for **{repo_name}**.\n\n"
                                    "Managed by [Codebase Cortex](https://github.com/sarupurisailalith/codebase-cortex)."
                                ),
                            }
                        ],
                    },
                )
                parent_id = extract_page_id(result)
                if parent_id:
                    cache.upsert(parent_id, PARENT_PAGE_TITLE)
                    logger.info(f"Created parent page: {parent_title}")
                else:
                    logger.error("Failed to extract parent page ID from response")
                    return []
            except Exception as e:
                logger.error(f"Failed to create parent page: {e}")
                return []
        else:
            cache.upsert(parent_id, PARENT_PAGE_TITLE)
            logger.info(f"Found existing parent page: {PARENT_PAGE_TITLE}")

        # Step 3: Create child pages under parent
        for page_info in STARTER_PAGES:
            title = page_info["title"]
            display_title = f"{page_info['icon']} {title}"

            # Check cache first, then search Notion
            cached = cache.find_by_title(title)
            if cached:
                pages.append({"title": title, "page_id": cached.page_id})
                logger.info(f"Already exists (cached): {display_title}")
                continue

            existing_id = await search_page_by_title(session, title)
            if existing_id:
                cache.upsert(existing_id, title)
                pages.append({"title": title, "page_id": existing_id})
                logger.info(f"Found existing: {display_title}")
                continue

            # Create new page under parent
            await rate_limiter.acquire()
            try:
                content = (
                    f"# {title}\n\n"
                    f"{page_info['description']}\n\n"
                    "---\n*Auto-generated by Codebase Cortex*"
                )
                result = await session.call_tool(
                    "notion-create-pages",
                    arguments={
                        "parent": {"page_id": parent_id},
                        "pages": [
                            {
                                "properties": {"title": display_title},
                                "content": content,
                            }
                        ],
                    },
                )

                page_id = extract_page_id(result)
                if page_id:
                    cache.upsert(page_id, title)
                    pages.append({"title": title, "page_id": page_id})
                    logger.info(f"Created: {display_title}")
                else:
                    logger.error(f"Failed to extract page ID for '{title}'")

            except Exception as e:
                logger.error(f"Failed to create page '{title}': {e}")

    return pages
