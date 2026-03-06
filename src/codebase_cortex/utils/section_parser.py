"""Markdown section parser for section-level page updates."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Section:
    """A section of a markdown document."""

    heading: str  # Full heading line e.g. "## API Endpoints" (empty for preamble)
    level: int  # Number of # symbols (0 for preamble)
    content: str  # Content between this heading and the next

    @property
    def full_text(self) -> str:
        """Reconstruct the section as it appears in the document."""
        if self.heading and self.content:
            return f"{self.heading}\n{self.content}"
        return self.heading or self.content


def parse_sections(markdown: str) -> list[Section]:
    """Parse markdown into a flat list of sections split by headings.

    Each section contains the heading line and all content until the next heading.
    Content before the first heading becomes a preamble section with level 0.
    """
    if not markdown or not markdown.strip():
        return []

    lines = markdown.split("\n")
    sections: list[Section] = []
    current_heading = ""
    current_level = 0
    buffer: list[str] = []

    for line in lines:
        match = re.match(r"^(#{1,6})\s+", line)
        if match:
            # Flush previous section
            content = "\n".join(buffer).strip()
            if current_heading or content:
                sections.append(Section(
                    heading=current_heading,
                    level=current_level,
                    content=content,
                ))
            current_heading = line
            current_level = len(match.group(1))
            buffer = []
        else:
            buffer.append(line)

    # Flush last section
    content = "\n".join(buffer).strip()
    if current_heading or content:
        sections.append(Section(
            heading=current_heading,
            level=current_level,
            content=content,
        ))

    return sections


def normalize_heading(heading: str) -> str:
    """Normalize a heading for fuzzy comparison.

    Strips # symbols, extra whitespace, and lowercases.
    """
    stripped = re.sub(r"^#+\s*", "", heading).strip()
    return stripped.lower()


def merge_sections(
    existing_sections: list[Section],
    section_updates: list[dict],
) -> str:
    """Merge section-level updates into existing page content.

    For each update:
    - action "update": replaces the matching section's content (heading preserved)
    - action "create": appends as a new section at the end

    If an "update" heading doesn't match any existing section, it's appended
    as a new section (graceful fallback).

    Returns the full reconstructed page content.
    """
    update_map: dict[str, dict] = {}
    new_sections: list[dict] = []

    for update in section_updates:
        action = update.get("action", "update")
        if action == "create":
            new_sections.append(update)
        else:
            norm = normalize_heading(update.get("heading", ""))
            if norm:
                update_map[norm] = update

    result_parts: list[str] = []
    matched: set[str] = set()

    for section in existing_sections:
        norm = normalize_heading(section.heading) if section.heading else ""
        if norm and norm in update_map:
            update = update_map[norm]
            matched.add(norm)
            new_content = update.get("content", "").strip()
            # Keep original heading format, replace content
            if section.heading:
                result_parts.append(f"{section.heading}\n{new_content}")
            else:
                result_parts.append(new_content)
        else:
            result_parts.append(section.full_text)

    # Append unmatched "update" entries as new sections (heading not found)
    for norm, update in update_map.items():
        if norm not in matched:
            heading = update.get("heading", "")
            content = update.get("content", "").strip()
            if heading and content:
                result_parts.append(f"{heading}\n{content}")

    # Append explicitly new sections
    for new_sec in new_sections:
        heading = new_sec.get("heading", "")
        content = new_sec.get("content", "").strip()
        if heading and content:
            result_parts.append(f"{heading}\n{content}")
        elif content:
            result_parts.append(content)

    return "\n\n".join(part for part in result_parts if part.strip())
