"""DocBackend protocol — the abstraction layer between pipeline and output targets."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class DocBackend(Protocol):
    """Interface that all documentation backends implement.

    Every agent that writes documentation does so through this interface.
    The pipeline produces structured update instructions; the backend
    decides where and how to persist them.
    """

    async def fetch_page_list(self) -> list[dict]:
        """Return list of pages with titles, paths/IDs, and section heading trees.

        Each dict has at minimum: title, ref (file path or page ID),
        and sections (list of heading dicts).
        """
        ...

    async def fetch_section(
        self,
        page_ref: str,
        heading: str,
        line_range: tuple[int, int] | None = None,
    ) -> str:
        """Return content of a specific section within a page.

        Args:
            page_ref: File path (local) or page ID (remote).
            heading: The section heading to extract (e.g. "## Overview").
            line_range: Optional (start, end) line numbers for direct access.
                        Falls back to heading-based extraction if stale.
        """
        ...

    async def write_page(
        self,
        page_ref: str,
        title: str,
        content: str,
        action: str,
    ) -> str:
        """Write a full page. Returns page reference (file path or remote ID).

        Args:
            page_ref: File path (local) or page ID (remote). Empty for new pages.
            title: Page title.
            content: Full markdown content.
            action: "create" or "update".
        """
        ...

    async def write_section(
        self,
        page_ref: str,
        heading: str,
        content: str,
    ) -> None:
        """Write a single section within a page.

        Default implementation: read full page, merge section, write back.
        """
        ...

    async def create_task(
        self,
        task: dict,
        parent_ref: str | None = None,
    ) -> None:
        """Create a task item in the configured format.

        Args:
            task: Dict with title, description, priority keys.
            parent_ref: Optional parent page/section reference.
        """
        ...

    async def append_to_log(self, page_ref: str, content: str) -> None:
        """Append content to a log page (preserves existing content).

        Used by SprintReporter for sprint summaries.
        """
        ...

    async def search_pages(self, query: str) -> list[dict]:
        """Search pages by title or content.

        Optional — backends without search capability return [].
        """
        ...
