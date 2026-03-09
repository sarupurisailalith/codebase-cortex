"""Documentation backends — abstraction layer between pipeline and output targets.

Use ``get_backend(settings)`` to obtain the correct backend for the current
configuration. Agents should never import a backend class directly; they
receive the backend through state or dependency injection.
"""

from __future__ import annotations

from codebase_cortex.backends.protocol import DocBackend
from codebase_cortex.config import Settings


def get_backend(settings: Settings) -> DocBackend:
    """Return the configured documentation backend.

    Reads ``settings.doc_output`` to decide which implementation to use:
    - ``"local"`` → LocalMarkdownBackend (default)
    - ``"notion"`` → NotionBackend
    """
    if settings.doc_output == "notion":
        from codebase_cortex.backends.notion_backend import NotionBackend
        return NotionBackend(settings)

    if settings.doc_output == "local":
        from codebase_cortex.backends.local_markdown import LocalMarkdownBackend
        return LocalMarkdownBackend(settings)

    raise ValueError(
        f"Unknown doc_output backend: {settings.doc_output!r}. "
        "Expected 'local' or 'notion'."
    )


__all__ = ["DocBackend", "get_backend"]
