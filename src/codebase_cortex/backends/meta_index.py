"""MetaIndex — reads/writes .cortex-meta.json for structural metadata."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path


def _md5(text: str) -> str:
    """Compute MD5 hash of text, return hex string."""
    return hashlib.md5(text.encode()).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MetaIndex:
    """Manages the .cortex-meta.json structural metadata file.

    This file tracks page structure, section hashes (for human-edit detection),
    line ranges, timestamps, and run metrics.
    """

    def __init__(self, docs_dir: Path) -> None:
        self.docs_dir = docs_dir
        self.meta_path = docs_dir / ".cortex-meta.json"
        self._data: dict = {}

    def load(self) -> dict:
        """Load .cortex-meta.json from disk. Returns the data dict."""
        if self.meta_path.exists():
            self._data = json.loads(self.meta_path.read_text())
        else:
            self._data = self._empty_meta()
        return self._data

    def save(self) -> None:
        """Write current data to .cortex-meta.json."""
        self.docs_dir.mkdir(parents=True, exist_ok=True)
        self._data["generated_at"] = _now_iso()
        self.meta_path.write_text(json.dumps(self._data, indent=2) + "\n")

    @property
    def data(self) -> dict:
        if not self._data:
            self.load()
        return self._data

    def _empty_meta(self) -> dict:
        """Return a fresh meta index structure."""
        return {
            "version": 2,
            "repo": self.docs_dir.parent.name,
            "detail_level": "standard",
            "generated_at": _now_iso(),
            "scope": {"include": [], "exclude": []},
            "pages": {},
            "tasks": {"total": 0, "by_priority": {}},
            "sprint_log": {"latest_entry": None, "total_entries": 0},
            "last_run": None,
        }

    # --- Page operations ---

    def get_page(self, page: str) -> dict | None:
        """Get page metadata by filename."""
        return self.data.get("pages", {}).get(page)

    def set_page(
        self,
        page: str,
        title: str,
        source_commit: str = "",
        is_draft: bool = False,
    ) -> dict:
        """Create or update a page entry. Returns the page dict."""
        pages = self.data.setdefault("pages", {})
        if page not in pages:
            pages[page] = {
                "title": title,
                "content_hash": "",
                "last_updated": _now_iso(),
                "source_commit": source_commit,
                "is_draft": is_draft,
                "sections": [],
            }
        else:
            pages[page]["title"] = title
            pages[page]["last_updated"] = _now_iso()
            if source_commit:
                pages[page]["source_commit"] = source_commit
        return pages[page]

    # --- Section operations ---

    def get_section_tree(self, page: str) -> list[dict]:
        """Return the section heading tree for a page."""
        page_data = self.get_page(page)
        if page_data:
            return page_data.get("sections", [])
        return []

    def get_section_hashes(
        self, page: str, heading: str
    ) -> tuple[str, str]:
        """Return (content_hash, cortex_hash) for a section."""
        for section in self.get_section_tree(page):
            if section.get("heading") == heading:
                return (
                    section.get("content_hash", ""),
                    section.get("cortex_hash", ""),
                )
        return ("", "")

    def is_human_edited(self, page: str, heading: str) -> bool:
        """Check if a section has been edited by a human since last Cortex run.

        Returns True when content_hash != cortex_hash (and both are set).
        """
        content_hash, cortex_hash = self.get_section_hashes(page, heading)
        if not content_hash or not cortex_hash:
            return False
        return content_hash != cortex_hash

    def update_section(
        self,
        page: str,
        heading: str,
        content_hash: str,
        cortex_hash: str,
        line_range: tuple[int, int],
        source_commit: str = "",
    ) -> None:
        """Create or update a section entry within a page."""
        page_data = self.data.get("pages", {}).get(page)
        if not page_data:
            return

        # Parse heading level
        level_match = re.match(r"^(#{1,6})\s+", heading)
        level = len(level_match.group(1)) if level_match else 0

        sections = page_data.setdefault("sections", [])

        # Find existing section
        for section in sections:
            if section.get("heading") == heading:
                section["content_hash"] = content_hash
                section["cortex_hash"] = cortex_hash
                section["line_range"] = list(line_range)
                section["last_updated"] = _now_iso()
                if source_commit:
                    section["source_commit"] = source_commit
                return

        # New section
        sections.append({
            "heading": heading,
            "level": level,
            "content_hash": content_hash,
            "cortex_hash": cortex_hash,
            "line_range": list(line_range),
            "source_commit": source_commit,
            "last_updated": _now_iso(),
        })

    # --- Metrics ---

    def update_run_metrics(self, metrics: dict) -> None:
        """Store the last run's metrics."""
        self.data["last_run"] = {
            "timestamp": _now_iso(),
            **metrics,
        }

    # --- Bulk operations ---

    def compute_content_hashes(self) -> None:
        """Recompute content_hash for all sections from files on disk.

        Reads each doc file, parses sections, and updates content_hash.
        Does NOT touch cortex_hash (that only changes when Cortex writes).
        """
        from codebase_cortex.utils.section_parser import parse_sections

        for page_name, page_data in self.data.get("pages", {}).items():
            file_path = self.docs_dir / page_name
            if not file_path.exists():
                continue

            content = file_path.read_text()
            parsed = parse_sections(content)
            lines = content.split("\n")

            # Build heading -> (content, line_range) map
            line_offset = 0
            for section in parsed:
                full = section.full_text
                # Find line range
                start = line_offset
                section_lines = full.count("\n") + 1
                end = start + section_lines
                line_offset = end

                if not section.heading:
                    continue

                section_content = section.content.strip()
                new_hash = _md5(section_content) if section_content else ""

                # Update in meta
                for meta_section in page_data.get("sections", []):
                    if meta_section.get("heading") == section.heading:
                        meta_section["content_hash"] = new_hash
                        meta_section["line_range"] = [start + 1, end]
                        break

    def initialize_from_files(self) -> None:
        """Scan docs/ directory and build meta index from existing markdown files.

        Used for first-time setup or rebuilding a corrupted meta index.
        """
        from codebase_cortex.utils.section_parser import parse_sections

        self._data = self._empty_meta()

        for md_file in sorted(self.docs_dir.glob("*.md")):
            if md_file.name.startswith("."):
                continue

            content = md_file.read_text()
            parsed = parse_sections(content)

            # Extract title from first heading
            title = md_file.stem.replace("-", " ").title()
            for section in parsed:
                if section.heading and section.level == 1:
                    title = re.sub(r"^#\s*", "", section.heading).strip()
                    break

            page_data = self.set_page(md_file.name, title)

            # Build sections
            line_offset = 0
            for section in parsed:
                full = section.full_text
                section_lines = full.count("\n") + 1
                start = line_offset + 1
                end = line_offset + section_lines
                line_offset += section_lines

                if not section.heading:
                    continue

                section_content = section.content.strip()
                content_hash = _md5(section_content) if section_content else ""

                page_data.setdefault("sections", []).append({
                    "heading": section.heading,
                    "level": section.level,
                    "content_hash": content_hash,
                    "cortex_hash": content_hash,  # Baseline: both equal
                    "line_range": [start, end],
                    "source_commit": "",
                    "last_updated": _now_iso(),
                })

            # Compute full page hash
            page_data["content_hash"] = _md5(content)
