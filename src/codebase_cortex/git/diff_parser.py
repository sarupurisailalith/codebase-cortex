"""Parse git diffs into structured data."""

from __future__ import annotations

import re

from git import Repo

from codebase_cortex.state import FileChange


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
        # Only one commit — diff against empty tree
        return repo.git.diff("4b825dc642cb6eb9a060e54bf899d15363d7ef21", "HEAD")

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
