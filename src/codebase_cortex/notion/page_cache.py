"""Local cache for Notion page metadata with staleness tracking."""

from __future__ import annotations

import json
import time
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class CachedPage:
    """A cached Notion page entry."""

    page_id: str
    title: str
    last_synced: float
    content_hash: str = ""

    def is_stale(self, max_age: float = 3600.0) -> bool:
        """Check if the cache entry is older than max_age seconds."""
        return (time.time() - self.last_synced) > max_age


@dataclass
class PageCache:
    """In-memory cache of Notion pages, backed by a JSON file."""

    cache_path: Path
    pages: dict[str, CachedPage] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._load()

    def _load(self) -> None:
        if self.cache_path.exists():
            data = json.loads(self.cache_path.read_text())
            self.pages = {
                pid: CachedPage(**entry) for pid, entry in data.items()
            }

    def save(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            pid: {
                "page_id": p.page_id,
                "title": p.title,
                "last_synced": p.last_synced,
                "content_hash": p.content_hash,
            }
            for pid, p in self.pages.items()
        }
        self.cache_path.write_text(json.dumps(data, indent=2))

    def upsert(self, page_id: str, title: str, content_hash: str = "") -> None:
        self.pages[page_id] = CachedPage(
            page_id=page_id,
            title=title,
            last_synced=time.time(),
            content_hash=content_hash,
        )
        self.save()

    def get(self, page_id: str) -> CachedPage | None:
        return self.pages.get(page_id)

    def get_stale(self, max_age: float = 3600.0) -> list[CachedPage]:
        return [p for p in self.pages.values() if p.is_stale(max_age)]

    def find_by_title(self, title: str) -> CachedPage | None:
        for page in self.pages.values():
            if page.title == title:
                return page
        return None
