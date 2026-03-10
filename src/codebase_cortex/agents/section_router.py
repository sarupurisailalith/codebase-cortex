"""SectionRouter agent — lightweight triage to identify sections needing updates."""

from __future__ import annotations

from codebase_cortex.agents.base import BaseAgent
from codebase_cortex.backends import get_backend
from codebase_cortex.backends.meta_index import MetaIndex
from codebase_cortex.config import Settings
from codebase_cortex.state import CortexState
from codebase_cortex.utils.json_parsing import parse_json_array

SYSTEM_PROMPT = """You are a documentation triage specialist. Given a code analysis and a
documentation section tree, identify which documentation sections need updating.

IMPORTANT: You read ONLY the section headings and structure — NOT the section content.
Your job is to determine WHICH sections are affected, not to write the documentation.

Output a JSON array. Each element has:
- "page": filename (e.g. "architecture.md")
- "section": heading (e.g. "## API Endpoints")
- "reason": brief explanation of why this section needs updating
- "priority": "high" (breaking changes, new APIs), "medium" (new features), "low" (minor changes)

Special cases:
- If a new page should be created, use: {"action": "create_page", "title": "Suggested Title", "sections": ["## Section1", "## Section2"], "reason": "..."}
- If the change is purely internal (refactoring, formatting) with no doc impact, return an empty array: []

Only include sections that genuinely need updating based on the code changes.
Respond with ONLY the JSON array."""


class SectionRouterAgent(BaseAgent):
    """Lightweight triage: identifies which doc sections need updating.

    Reads only headings and structure (not full content) to minimize
    LLM input tokens. Also flags human-edited sections.
    """

    async def run(self, state: CortexState) -> dict:
        analysis = state.get("analysis", "")
        if not analysis:
            return {"targeted_sections": []}

        settings = self.settings
        full_scan = state.get("full_scan", False)
        backend = get_backend(settings)

        # Get page list with section trees
        pages = await backend.fetch_page_list()

        if not pages and not full_scan:
            return {"targeted_sections": []}

        if not pages and full_scan:
            # No docs yet but full scan — ask LLM to suggest initial pages
            pages = []  # Continue to prompt with empty section map

        # Build section heading map for the LLM
        # Check human-edited status via MetaIndex
        section_map_lines = []
        meta = None

        if hasattr(backend, "meta"):
            meta = backend.meta

        for page in pages:
            ref = page["ref"]
            title = page["title"]
            sections = page.get("sections", [])
            section_map_lines.append(f"\n### {title} ({ref})")
            for sec in sections:
                heading = sec.get("heading", "")
                if not heading:
                    continue
                human_flag = ""
                if meta and meta.is_human_edited(ref, heading):
                    human_flag = " [HUMAN-EDITED]"
                section_map_lines.append(f"  - {heading}{human_flag}")

        section_map = "\n".join(section_map_lines) if section_map_lines else "(no sections found)"

        # Build related docs summary
        related_docs = state.get("related_docs", [])
        related_summary = ""
        if related_docs:
            related_summary = "\n\n## Related Code Chunks\n"
            for doc in related_docs[:5]:
                related_summary += f"- {doc.get('title', 'unknown')} (similarity: {doc.get('similarity', 0):.2f})\n"

        full_scan_instruction = ""
        if full_scan:
            full_scan_instruction = """
IMPORTANT: This is a FULL SCAN (initial documentation generation). The codebase has little or no
documentation yet. You should suggest creating comprehensive documentation pages for ALL major
components. Use {"action": "create_page"} for each new page. Create pages for:
- Architecture/overview documentation
- API documentation (if the project has APIs)
- Data models documentation
- Key subsystem documentation
Do NOT log these as tasks — create the pages now."""

        prompt = f"""Review this code analysis and identify which documentation sections need updating.
{full_scan_instruction}

## Code Analysis
{analysis}
{related_summary}

## Documentation Structure (headings only)
{section_map}

Sections marked [HUMAN-EDITED] have been manually modified by a human since the last Cortex run.
Be cautious about overwriting these — only include them if the code changes are significant enough to warrant it.

Respond with a JSON array of sections to update. Return [] if no documentation impact."""

        try:
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
            raw = await self._invoke_llm(messages, node_name="section_router")
            targeted = parse_json_array(raw)
        except Exception as e:
            return {
                "targeted_sections": [],
                "errors": self._append_error(state, f"Section routing failed: {e}"),
            }

        # Enrich with human_edited flag
        if meta:
            for section in targeted:
                page = section.get("page", "")
                heading = section.get("section", "")
                if page and heading:
                    section["human_edited"] = meta.is_human_edited(page, heading)

        return {"targeted_sections": targeted}
