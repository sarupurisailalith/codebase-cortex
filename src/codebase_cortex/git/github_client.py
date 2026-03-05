"""GitHub client for remote repository access (optional)."""

from __future__ import annotations

from github import Github, Auth

from codebase_cortex.config import Settings


def get_github_client(settings: Settings) -> Github | None:
    """Create a GitHub client if a token is available.

    Returns None if no token is configured.
    """
    if not settings.github_token:
        return None
    return Github(auth=Auth.Token(settings.github_token))


def get_repo_info(settings: Settings) -> dict | None:
    """Get basic repository info from GitHub.

    Returns:
        Dict with repo name, description, default branch, etc.
        None if GitHub is not configured or repo_path is local.
    """
    client = get_github_client(settings)
    if client is None:
        return None

    repo_path = settings.repo_path
    if not repo_path.startswith("https://github.com"):
        return None

    # Extract owner/repo from URL
    parts = repo_path.rstrip("/").split("/")
    repo_name = f"{parts[-2]}/{parts[-1]}"

    repo = client.get_repo(repo_name)
    return {
        "name": repo.full_name,
        "description": repo.description,
        "default_branch": repo.default_branch,
        "language": repo.language,
        "stars": repo.stargazers_count,
    }
