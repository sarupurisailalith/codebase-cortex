"""CodeAnalyzer agent — analyzes git diffs and identifies what changed and why."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from codebase_cortex.agents.base import BaseAgent
from codebase_cortex.git.diff_parser import get_recent_diff, parse_diff
from codebase_cortex.state import CortexState

SYSTEM_PROMPT = """You are a senior software engineer analyzing code changes.
Given a git diff, provide a clear, structured analysis covering:

1. **Summary**: One-paragraph overview of what changed and why.
2. **Changed Components**: List each file/module changed with a brief description.
3. **Impact Assessment**: What parts of the system are affected? Any breaking changes?
4. **Documentation Needs**: What documentation should be created or updated?

Be concise but thorough. Focus on the "why" behind changes, not just the "what".
If the diff is too large, focus on the most significant changes."""


class CodeAnalyzerAgent(BaseAgent):
    """Analyzes git diffs to understand what changed and identify documentation needs."""

    async def run(self, state: CortexState) -> dict:
        # Get diff text — either from state or from repo
        diff_text = state.get("diff_text", "")
        if not diff_text:
            repo_path = state.get("repo_path", ".")
            try:
                diff_text = get_recent_diff(repo_path)
            except Exception as e:
                return {"errors": self._append_error(state, f"Failed to get diff: {e}")}

        if not diff_text:
            return {"analysis": "", "changed_files": []}

        # Parse structured file changes
        changed_files = parse_diff(diff_text)

        # Build LLM prompt
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

        # Call LLM
        try:
            messages = [
                SystemMessage(content=SYSTEM_PROMPT),
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
