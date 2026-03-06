"""Tests for the markdown section parser."""

from codebase_cortex.utils.section_parser import (
    Section,
    merge_sections,
    normalize_heading,
    parse_sections,
)


# --- parse_sections ---


def test_parse_sections_empty():
    assert parse_sections("") == []
    assert parse_sections("   ") == []
    assert parse_sections(None) == []


def test_parse_sections_preamble_only():
    sections = parse_sections("Just some text\nwith no headings.")
    assert len(sections) == 1
    assert sections[0].level == 0
    assert sections[0].heading == ""
    assert "Just some text" in sections[0].content


def test_parse_sections_single_heading():
    md = "## API Endpoints\nGET /users\nPOST /tasks"
    sections = parse_sections(md)
    assert len(sections) == 1
    assert sections[0].heading == "## API Endpoints"
    assert sections[0].level == 2
    assert "GET /users" in sections[0].content


def test_parse_sections_multiple_headings():
    md = """# Title

Intro paragraph.

## Section A
Content A here.

### Subsection A1
Sub content.

## Section B
Content B here."""
    sections = parse_sections(md)
    assert len(sections) == 4
    assert sections[0].heading == "# Title"
    assert sections[0].level == 1
    assert "Intro paragraph" in sections[0].content
    assert sections[1].heading == "## Section A"
    assert sections[2].heading == "### Subsection A1"
    assert sections[3].heading == "## Section B"


def test_parse_sections_preamble_before_first_heading():
    md = """Some preamble text.

## First Section
Content here."""
    sections = parse_sections(md)
    assert len(sections) == 2
    assert sections[0].level == 0
    assert sections[0].heading == ""
    assert "preamble" in sections[0].content
    assert sections[1].heading == "## First Section"


def test_section_full_text():
    s = Section(heading="## Test", level=2, content="Some content")
    assert s.full_text == "## Test\nSome content"

    preamble = Section(heading="", level=0, content="Just text")
    assert preamble.full_text == "Just text"

    empty = Section(heading="## Empty", level=2, content="")
    assert empty.full_text == "## Empty"


# --- normalize_heading ---


def test_normalize_heading():
    assert normalize_heading("## API Endpoints") == "api endpoints"
    assert normalize_heading("### Sub Section") == "sub section"
    assert normalize_heading("# TITLE") == "title"
    assert normalize_heading("####  Extra   Spaces ") == "extra   spaces"


# --- merge_sections ---


def test_merge_update_existing_section():
    existing = [
        Section(heading="## Overview", level=2, content="Old overview."),
        Section(heading="## API", level=2, content="Old API docs."),
    ]
    updates = [
        {"heading": "## API", "content": "New API docs.", "action": "update"},
    ]
    result = merge_sections(existing, updates)
    assert "## Overview" in result
    assert "Old overview." in result
    assert "## API" in result
    assert "New API docs." in result
    assert "Old API docs." not in result


def test_merge_create_new_section():
    existing = [
        Section(heading="## Overview", level=2, content="Existing stuff."),
    ]
    updates = [
        {"heading": "## New Section", "content": "Brand new.", "action": "create"},
    ]
    result = merge_sections(existing, updates)
    assert "## Overview" in result
    assert "## New Section" in result
    assert "Brand new." in result


def test_merge_unmatched_update_appended():
    """An update targeting a non-existent heading is appended (graceful fallback)."""
    existing = [
        Section(heading="## Overview", level=2, content="Existing."),
    ]
    updates = [
        {"heading": "## Missing", "content": "Fallback content.", "action": "update"},
    ]
    result = merge_sections(existing, updates)
    assert "## Overview" in result
    assert "## Missing" in result
    assert "Fallback content." in result


def test_merge_case_insensitive_heading_match():
    existing = [
        Section(heading="## API Endpoints", level=2, content="Old content."),
    ]
    updates = [
        {"heading": "## api endpoints", "content": "Updated.", "action": "update"},
    ]
    result = merge_sections(existing, updates)
    # Original heading format preserved
    assert "## API Endpoints" in result
    assert "Updated." in result
    assert "Old content." not in result


def test_merge_preserves_preamble():
    existing = [
        Section(heading="", level=0, content="Preamble text."),
        Section(heading="## Section", level=2, content="Body."),
    ]
    updates = [
        {"heading": "## Section", "content": "New body.", "action": "update"},
    ]
    result = merge_sections(existing, updates)
    assert "Preamble text." in result
    assert "New body." in result


def test_merge_mixed_updates_and_creates():
    existing = [
        Section(heading="## A", level=2, content="Content A."),
        Section(heading="## B", level=2, content="Content B."),
    ]
    updates = [
        {"heading": "## A", "content": "Updated A.", "action": "update"},
        {"heading": "## C", "content": "New C.", "action": "create"},
    ]
    result = merge_sections(existing, updates)
    assert "Updated A." in result
    assert "Content B." in result
    assert "## C" in result
    assert "New C." in result
