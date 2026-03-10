"""CodeAnalyzer agent — analyzes git diffs and identifies what changed and why."""

from __future__ import annotations

from codebase_cortex.agents.base import BaseAgent
from codebase_cortex.git.diff_parser import get_recent_diff, get_full_codebase_summary, parse_diff
from codebase_cortex.state import CortexState

DETAIL_LEVEL_INSTRUCTIONS = {
    "standard": (
        "Focus on module-level summaries. What changed and which components are affected. "
        "Keep descriptions brief — one paragraph per major component."
    ),
    "detailed": (
        "Include function-level analysis. Document parameters, return types, error conditions, "
        "and dependencies. Describe how components interact at the function/method level."
    ),
    "comprehensive": (
        "Include everything from detailed plus: implementation rationale, performance implications, "
        "edge cases, potential gotchas, and migration notes. Be extremely thorough."
    ),
}


def _build_diff_prompt(detail_level: str = "standard") -> str:
    detail_instructions = DETAIL_LEVEL_INSTRUCTIONS.get(detail_level, DETAIL_LEVEL_INSTRUCTIONS["standard"])

    return f"""You are a senior software engineer analyzing code changes.
Given a git diff, provide a clear, structured analysis covering:

1. **Summary**: One-paragraph overview of what changed and why.
2. **Changed Components**: List each file/module changed with a brief description.
3. **Impact Assessment**: What parts of the system are affected? Any breaking changes?
4. **Documentation Needs**: What documentation should be created or updated?

Detail level: {detail_level}
{detail_instructions}

Be concise but thorough. Focus on the "why" behind changes, not just the "what".
If the diff is too large, focus on the most significant changes."""


def _build_full_scan_prompt(detail_level: str = "standard") -> str:
    detail_instructions = DETAIL_LEVEL_INSTRUCTIONS.get(detail_level, DETAIL_LEVEL_INSTRUCTIONS["standard"])

    return f"""You are a senior software engineer analyzing an entire codebase.
Given a summary of all source files, provide a comprehensive analysis covering:

1. **Project Overview**: What this project does, its purpose and architecture.
2. **Components**: List each major module/package with its responsibility.
3. **Key APIs and Interfaces**: Public functions, classes, endpoints, and contracts.
4. **Architecture**: How components relate to each other, data flow, dependencies.
5. **Documentation Needs**: What documentation pages should be created?

Detail level: {detail_level}
{detail_instructions}

Be thorough — this is the initial documentation for a project that has none.
Focus on what a new developer would need to understand the codebase."""


class CodeAnalyzerAgent(BaseAgent):
    """Analyzes git diffs or full codebases to identify documentation needs."""

    async def run(self, state: CortexState) -> dict:
        full_scan = state.get("full_scan", False)
        repo_path = state.get("repo_path", ".")

        if full_scan:
            return await self._run_full_scan(state, repo_path)
        return await self._run_diff(state, repo_path)

    async def _run_diff(self, state: CortexState, repo_path: str) -> dict:
        """Analyze the most recent git diff."""
        diff_text = state.get("diff_text", "")
        if not diff_text:
            try:
                diff_text = get_recent_diff(repo_path)
            except Exception as e:
                return {"errors": self._append_error(state, f"Failed to get diff: {e}")}

        if not diff_text:
            return {"analysis": "", "changed_files": []}

        changed_files = parse_diff(diff_text)
        detail_level = state.get("detail_level", "standard")

        file_summary = "\n".join(
            f"- {f['path']} ({f['status']}: +{f['additions']}/-{f['deletions']})"
            for f in changed_files
        )

        prompt = f"""Analyze the following code changes:

## Files Changed
{file_summary}

## Full Diff
```
{diff_text[:15000]}
```"""

        try:
            messages = [
                {"role": "system", "content": _build_diff_prompt(detail_level)},
                {"role": "user", "content": prompt},
            ]
            analysis = await self._invoke_llm(messages, node_name="code_analyzer")
        except Exception as e:
            return {
                "diff_text": diff_text,
                "changed_files": changed_files,
                "errors": self._append_error(state, f"LLM analysis failed: {e}"),
            }

        return {
            "diff_text": diff_text,
            "changed_files": changed_files,
            "analysis": analysis,
        }

    async def _run_full_scan(self, state: CortexState, repo_path: str) -> dict:
        """Analyze the entire codebase for initial documentation."""
        try:
            summary = get_full_codebase_summary(repo_path)
        except Exception as e:
            return {"errors": self._append_error(state, f"Failed to scan codebase: {e}")}

        if not summary:
            return {"analysis": "", "changed_files": []}

        detail_level = state.get("detail_level", "standard")

        prompt = f"""Analyze this entire codebase and produce a comprehensive analysis for documentation:

{summary}"""

        try:
            messages = [
                {"role": "system", "content": _build_full_scan_prompt(detail_level)},
                {"role": "user", "content": prompt},
            ]
            analysis = await self._invoke_llm(messages, node_name="code_analyzer")
        except Exception as e:
            return {
                "errors": self._append_error(state, f"LLM analysis failed: {e}"),
            }

        return {
            "analysis": analysis,
            "changed_files": [],
        }
