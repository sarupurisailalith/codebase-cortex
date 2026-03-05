"""Parse git diffs into structured data."""

from __future__ import annotations

import os
import re

from git import Repo

from codebase_cortex.state import FileChange

CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs",
    ".rb", ".php", ".c", ".cpp", ".h", ".hpp", ".cs", ".swift",
    ".kt", ".scala", ".sh", ".bash", ".yml", ".yaml", ".toml",
    ".json", ".md", ".rst", ".txt",
}
SKIP_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__",
    ".pytest_cache", "dist", "build", ".eggs", ".tox",
    ".mypy_cache", ".ruff_cache", ".cortex",
}


def get_recent_diff(repo_path: str, commits: int = 1) -> str:
    """Get the unified diff for the most recent commit(s).

    Args:
        repo_path: Path to the git repository.
        commits: Number of recent commits to include.

    Returns:
        Unified diff text, or empty string if no commits.
    """
    repo = Repo(repo_path)
    if repo.head.is_detached or not list(repo.iter_commits(max_count=1)):
        return ""

    commits_list = list(repo.iter_commits(max_count=commits + 1))
    if len(commits_list) < 2:
        # Only one commit — show the root commit diff
        return repo.git.diff_tree("--root", "--patch", "HEAD")

    old = commits_list[-1]
    return repo.git.diff(old.hexsha, "HEAD")


def get_staged_diff(repo_path: str) -> str:
    """Get the diff of currently staged changes.

    Args:
        repo_path: Path to the git repository.

    Returns:
        Unified diff of staged changes.
    """
    repo = Repo(repo_path)
    return repo.git.diff("--cached")


def parse_diff(diff_text: str) -> list[FileChange]:
    """Parse unified diff text into structured FileChange objects.

    Args:
        diff_text: Raw unified diff output.

    Returns:
        List of FileChange dicts with path, status, additions, deletions, diff.
    """
    if not diff_text.strip():
        return []

    files: list[FileChange] = []
    # Split on diff headers
    file_diffs = re.split(r"(?=^diff --git )", diff_text, flags=re.MULTILINE)

    for file_diff in file_diffs:
        if not file_diff.strip():
            continue

        # Extract file path
        header_match = re.match(r"diff --git a/(.*?) b/(.*)", file_diff)
        if not header_match:
            continue

        old_path = header_match.group(1)
        new_path = header_match.group(2)

        # Determine status
        if "new file mode" in file_diff:
            status = "added"
        elif "deleted file mode" in file_diff:
            status = "deleted"
        elif old_path != new_path:
            status = "renamed"
        else:
            status = "modified"

        # Count additions and deletions
        additions = 0
        deletions = 0
        for line in file_diff.split("\n"):
            if line.startswith("+") and not line.startswith("+++"):
                additions += 1
            elif line.startswith("-") and not line.startswith("---"):
                deletions += 1

        files.append(
            FileChange(
                path=new_path,
                status=status,
                additions=additions,
                deletions=deletions,
                diff=file_diff,
            )
        )

    return files


def get_full_codebase_summary(repo_path: str) -> str:
    """Walk all source files in a repo and build a virtual diff summary.

    This is intended for documenting existing projects that have no
    documentation yet.  It produces a structured text block that looks
    like a diff and can be passed directly to the CodeAnalyzer LLM.

    Args:
        repo_path: Absolute path to the root of the repository.

    Returns:
        A formatted string summarising every source file (path, line
        count, first 200 lines).  The total output is truncated to
        ~50 000 characters to stay within LLM context limits.
    """
    max_chars = 50_000
    max_preview_lines = 200

    parts: list[str] = []
    file_count = 0

    for dirpath, dirnames, filenames in os.walk(repo_path):
        # Prune directories we should skip (in-place so os.walk skips them)
        dirnames[:] = [
            d for d in dirnames if d not in SKIP_DIRS
        ]

        for filename in sorted(filenames):
            ext = os.path.splitext(filename)[1]
            if ext not in CODE_EXTENSIONS:
                continue

            full_path = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(full_path, repo_path)

            try:
                with open(full_path, "r", encoding="utf-8", errors="replace") as fh:
                    lines = fh.readlines()
            except (OSError, UnicodeDecodeError):
                continue

            line_count = len(lines)
            preview = "".join(lines[:max_preview_lines])
            if line_count > max_preview_lines:
                preview += f"\n... ({line_count - max_preview_lines} more lines)\n"

            entry = (
                f"--- /dev/null\n"
                f"+++ b/{rel_path}\n"
                f"## File: {rel_path} | {line_count} lines\n"
                f"{preview}\n"
            )
            parts.append(entry)
            file_count += 1

    header = (
        f"# Full Codebase Summary — {file_count} files\n"
        f"# Repository: {repo_path}\n\n"
    )
    body = header + "\n".join(parts)

    if len(body) > max_chars:
        body = body[:max_chars] + "\n\n... [truncated at 50000 characters]\n"

    return body
