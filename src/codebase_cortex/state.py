"""CortexState — shared state for the LangGraph pipeline."""

from __future__ import annotations

from typing import TypedDict


class FileChange(TypedDict):
    """A single file change extracted from a diff."""

    path: str
    status: str  # "added" | "modified" | "deleted" | "renamed"
    additions: int
    deletions: int
    diff: str


class DocUpdate(TypedDict):
    """A documentation update to apply via DocBackend."""

    page_id: str | None  # None = create new page (v0.1 compat)
    page_path: str | None  # Local file path (v0.2)
    title: str
    content: str
    action: str  # "create" | "update"
    sections_updated: list[str]  # Headings updated (v0.2)
    validation_needed: bool  # Flag for DocValidator (v0.2)


class TaskItem(TypedDict):
    """A task/ticket to create in Notion."""

    title: str
    description: str
    priority: str  # "high" | "medium" | "low"


class RelatedDoc(TypedDict, total=False):
    """A semantically related existing document."""

    page_id: str
    title: str
    similarity: float
    content: str  # Code chunk content for LLM context


class CortexState(TypedDict, total=False):
    """Shared state flowing through the LangGraph pipeline.

    Fields are populated progressively by each agent node.
    """

    # Input / trigger
    trigger: str  # "commit" | "pr" | "schedule" | "manual"
    repo_path: str
    dry_run: bool
    full_scan: bool  # True = analyze entire codebase, not just recent diff

    # Git data
    diff_text: str
    changed_files: list[FileChange]

    # CodeAnalyzer output
    analysis: str

    # SemanticFinder output
    related_docs: list[RelatedDoc]

    # DocWriter output
    doc_updates: list[DocUpdate]

    # TaskCreator output
    tasks_created: list[TaskItem]

    # SprintReporter output
    sprint_summary: str

    # Pipeline metadata
    errors: list[str]
    mcp_tools: list

    # v0.2 — Configuration & routing
    detail_level: str  # "standard" | "detailed" | "comprehensive"
    doc_strategy: str  # "main-only" | "branch-aware"
    output_mode: str  # "apply" | "propose" | "dry-run"
    backend: str  # "local" | "notion" | "confluence"
    sync_target: str  # Optional secondary sync target
    source_commit: str  # Git SHA that triggered this run
    branch: str  # Current branch name
    scope: str  # Monorepo scope (if configured)

    # v0.2 — SectionRouter output
    targeted_sections: list[dict]  # Includes human_edited flags

    # v0.2 — DocValidator output
    validated_updates: list[dict]  # doc_updates with confidence scores
    validation_issues: list[dict]  # Flagged problems

    # v0.2 — Run metrics
    run_metrics: dict  # Serialized RunMetrics
