"""CodeAnalyzer agent — analyzes git diffs and identifies what changed and why."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from codebase_cortex.agents.base import BaseAgent
from codebase_cortex.git.diff_parser import get_recent_diff, get_full_codebase_summary, parse_diff
from codebase_cortex.state import CortexState

DIFF_SYSTEM_PROMPT = """You are a senior software engineer analyzing code changes.
Given a git diff, provide a clear, structured analysis covering:

1. **Summary**: One-paragraph overview of what changed and why.
2. **Changed Components**: List each file/module changed with a brief description.
3. **Impact Assessment**: What parts of the system are affected? Any breaking changes?
4. **Documentation Needs**: What documentation should be created or updated?

Be concise but thorough. Focus on the "why" behind changes, not just the "what".
If the diff is too large, focus on the most significant changes."""

FULL_SYSTEM_PROMPT = """You are a senior software engineer analyzing an entire codebase.
Given a summary of all source files, provide a comprehensive analysis covering:

1. **Project Overview**: What this project does, its purpose and architecture.
2. **Components**: List each major module/package with its responsibility.
3. **Key APIs and Interfaces**: Public functions, classes, endpoints, and contracts.
4. **Architecture**: How components relate to each other, data flow, dependencies.
5. **Documentation Needs**: What documentation pages should be created?

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
                SystemMessage(content=DIFF_SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ]
            response = await self.llm.ainvoke(messages)
            analysis = response.content
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

        prompt = f"""Analyze this entire codebase and produce a comprehensive analysis for documentation:

{summary}"""

        try:
            messages = [
                SystemMessage(content=FULL_SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ]
            response = await self.llm.ainvoke(messages)
            analysis = response.content
        except Exception as e:
            return {
                "errors": self._append_error(state, f"LLM analysis failed: {e}"),
            }

        return {
            "analysis": analysis,
            "changed_files": [],
        }
