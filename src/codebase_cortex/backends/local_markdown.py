"""LocalMarkdownBackend — reads/writes documentation as local markdown files."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from codebase_cortex.backends.meta_index import MetaIndex
from codebase_cortex.config import Settings
from codebase_cortex.utils.section_parser import merge_sections, parse_sections, normalize_heading


class LocalMarkdownBackend:
    """Default backend: reads from and writes to the docs/ directory."""

    def __init__(self, settings: Settings) -> None:
        self.docs_dir = Path(settings.repo_path) / "docs"
        self.docs_dir.mkdir(exist_ok=True)
        self.meta = MetaIndex(self.docs_dir)
        self.meta.load()

    async def fetch_page_list(self) -> list[dict]:
        """Return list of pages with titles and section trees.

        Reads from .cortex-meta.json if available, otherwise scans docs/*.md.
        """
        if not self.meta.data.get("pages"):
            self.meta.initialize_from_files()

        result = []
        for filename, page_data in self.meta.data.get("pages", {}).items():
            result.append({
                "ref": filename,
                "title": page_data.get("title", filename),
                "sections": page_data.get("sections", []),
            })
        return result

    async def fetch_section(
        self,
        page_ref: str,
        heading: str,
        line_range: tuple[int, int] | None = None,
    ) -> str:
        """Return content of a specific section from a local markdown file.

        Tries line_range first for speed, falls back to heading-based extraction.
        """
        file_path = self.docs_dir / page_ref
        if not file_path.exists():
            return ""

        content = file_path.read_text()

        # Try line-range extraction first
        if line_range:
            lines = content.split("\n")
            start, end = line_range
            # Convert 1-indexed to 0-indexed
            start_idx = max(0, start - 1)
            end_idx = min(len(lines), end)
            extracted = "\n".join(lines[start_idx:end_idx])
            # Verify the heading is actually there (line ranges can go stale)
            if heading and normalize_heading(heading) in normalize_heading(extracted.split("\n")[0] if extracted else ""):
                return extracted

        # Fallback: parse sections and match by heading
        sections = parse_sections(content)
        target = normalize_heading(heading)
        for section in sections:
            if section.heading and normalize_heading(section.heading) == target:
                return section.content
        return ""

    async def write_page(
        self,
        page_ref: str,
        title: str,
        content: str,
        action: str,
    ) -> str:
        """Write a full page to docs/. Returns the file path."""
        if not page_ref:
            # Generate filename from title
            page_ref = self._slugify(title) + ".md"

        file_path = self.docs_dir / page_ref
        file_path.write_text(content)

        # Update meta index
        self.meta.set_page(page_ref, title)
        self._update_sections_meta(page_ref, content, cortex_written=True)
        self.meta.save()

        return page_ref

    async def write_section(
        self,
        page_ref: str,
        heading: str,
        content: str,
    ) -> None:
        """Write a single section: read full page, merge, write back."""
        file_path = self.docs_dir / page_ref
        if not file_path.exists():
            # Create a minimal page with just this section
            full_content = f"{heading}\n{content}"
            await self.write_page(page_ref, heading.lstrip("# "), full_content, "create")
            return

        existing = file_path.read_text()
        existing_sections = parse_sections(existing)
        merged = merge_sections(
            existing_sections,
            [{"heading": heading, "content": content, "action": "update"}],
        )
        file_path.write_text(merged)

        # Update meta
        self._update_sections_meta(page_ref, merged, cortex_written=True)
        self.meta.save()

    async def create_task(
        self,
        task: dict,
        parent_ref: str | None = None,
    ) -> None:
        """Append a task entry to docs/task-board.md."""
        task_file = self.docs_dir / "task-board.md"

        priority = task.get("priority", "medium")
        title = task.get("title", "Untitled task")
        description = task.get("description", "")
        priority_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(priority, "⚪")

        entry = f"- [{priority}] {priority_icon} **{title}**"
        if description:
            entry += f"\n  {description}"

        if task_file.exists():
            existing = task_file.read_text()
            task_file.write_text(existing.rstrip() + "\n" + entry + "\n")
        else:
            header = "# Documentation Tasks\n\n"
            task_file.write_text(header + entry + "\n")

        # Update task counts in meta
        tasks_meta = self.meta.data.setdefault("tasks", {"total": 0, "by_priority": {}})
        tasks_meta["total"] = tasks_meta.get("total", 0) + 1
        bp = tasks_meta.setdefault("by_priority", {})
        bp[priority] = bp.get(priority, 0) + 1
        self.meta.save()

    async def append_to_log(self, page_ref: str, content: str) -> None:
        """Append content to sprint-log.md with a date separator."""
        log_file = self.docs_dir / (page_ref or "sprint-log.md")

        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        separator = f"\n---\n\n## {date_str}\n\n"

        if log_file.exists():
            existing = log_file.read_text()
            log_file.write_text(existing.rstrip() + separator + content + "\n")
        else:
            header = "# Sprint Log\n"
            log_file.write_text(header + separator + content + "\n")

        # Update sprint_log in meta
        sprint_meta = self.meta.data.setdefault(
            "sprint_log", {"latest_entry": None, "total_entries": 0}
        )
        sprint_meta["latest_entry"] = date_str
        sprint_meta["total_entries"] = sprint_meta.get("total_entries", 0) + 1
        self.meta.save()

    async def search_pages(self, query: str) -> list[dict]:
        """Simple substring search across file contents and titles."""
        results = []
        query_lower = query.lower()

        for md_file in self.docs_dir.glob("*.md"):
            if md_file.name.startswith("."):
                continue
            content = md_file.read_text()
            if query_lower in content.lower() or query_lower in md_file.stem.lower():
                results.append({
                    "ref": md_file.name,
                    "title": md_file.stem.replace("-", " ").title(),
                })
        return results

    # --- Helpers ---

    def _update_sections_meta(
        self, page_ref: str, content: str, cortex_written: bool = False
    ) -> None:
        """Parse a page's content and update section metadata."""
        sections = parse_sections(content)
        lines = content.split("\n")

        line_offset = 0
        for section in sections:
            full = section.full_text
            section_lines = full.count("\n") + 1
            start = line_offset + 1
            end = line_offset + section_lines
            line_offset += section_lines

            if not section.heading:
                continue

            section_content = section.content.strip()
            content_hash = hashlib.md5(section_content.encode()).hexdigest()
            cortex_hash = content_hash if cortex_written else ""

            # Get existing cortex_hash if not cortex_written
            if not cortex_written:
                _, existing_cortex = self.meta.get_section_hashes(page_ref, section.heading)
                cortex_hash = existing_cortex

            self.meta.update_section(
                page=page_ref,
                heading=section.heading,
                content_hash=content_hash,
                cortex_hash=cortex_hash,
                line_range=(start, end),
            )

    @staticmethod
    def _slugify(title: str) -> str:
        """Convert a title to a filename-safe slug."""
        import re
        slug = title.lower().strip()
        slug = re.sub(r"[^\w\s-]", "", slug)
        slug = re.sub(r"[\s_]+", "-", slug)
        slug = re.sub(r"-+", "-", slug).strip("-")
        return slug or "untitled"
