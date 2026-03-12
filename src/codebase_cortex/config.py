"""Configuration and LLM factory for Codebase Cortex."""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

CORTEX_DIR_NAME = ".cortex"

logger = logging.getLogger("cortex")


def find_cortex_dir(start: Path | None = None) -> Path:
    """Find the .cortex directory, starting from the given path or cwd.

    Returns the .cortex path (may not exist yet — for `cortex init`).
    """
    start = start or Path.cwd()
    return start.resolve() / CORTEX_DIR_NAME


# v0.1 compat — kept for reference during migration
DEFAULT_MODELS: dict[str, str] = {
    "google": "gemini-2.5-flash-lite",
    "anthropic": "claude-sonnet-4-20250514",
    "openrouter": "",  # no sensible default — user must choose
}

RECOMMENDED_MODELS: dict[str, list[str]] = {
    "google": [
        "gemini/gemini-2.5-flash-lite",
        "gemini/gemini-2.5-flash",
        "gemini/gemini-2.5-pro",
    ],
    "anthropic": [
        "anthropic/claude-sonnet-4-20250514",
        "anthropic/claude-haiku-4-5-20251001",
    ],
    "openrouter": [
        "openrouter/anthropic/claude-sonnet-4",
        "openrouter/google/gemini-2.5-flash-lite",
    ],
}


@dataclass
class Settings:
    """Application settings loaded from .cortex/.env in the target repo."""

    # v0.2 LLM config (LiteLLM provider/model format)
    llm_model: str = "gemini/gemini-2.5-flash-lite"
    llm_api_base: str | None = None
    llm_api_key: str | None = None
    llm_fallback: str | None = None

    # Per-node model overrides
    llm_model_code_analyzer: str | None = None
    llm_model_section_router: str | None = None
    llm_model_doc_writer: str | None = None
    llm_model_doc_validator: str | None = None

    # v0.2 documentation config
    doc_output: str = "local"  # "local" | "notion"
    doc_sync: str | None = None
    doc_detail_level: str = "standard"  # "standard" | "detailed" | "comprehensive"
    doc_strategy: str = "main-only"  # "main-only" | "branch-aware"
    doc_output_mode: str = "apply"  # "apply" | "propose" | "dry-run"
    doc_scope: str | None = None
    doc_scope_exclude: str | None = None
    doc_auto_sync: bool = False
    doc_sync_targets: str = ""  # comma-separated: "notion", "notion,gitbook", etc.

    # MCP server mode
    mcp_server_enabled: bool = False
    mcp_agent: str = ""  # "claude-code" | "cursor" | "windsurf" | ""

    # v0.1 compat fields (kept for backward compat, deprecated)
    llm_provider: str = ""  # Deprecated — use llm_model provider/model format
    google_api_key: str = ""
    anthropic_api_key: str = ""
    openrouter_api_key: str = ""

    # Shared
    github_token: str = ""
    repo_path: Path = field(default_factory=lambda: Path.cwd())
    cortex_dir: Path = field(default_factory=lambda: find_cortex_dir())
    oauth_callback_port: int = 9876

    @property
    def data_dir(self) -> Path:
        return self.cortex_dir

    @property
    def notion_token_path(self) -> Path:
        return self.cortex_dir / "notion_tokens.json"

    @property
    def faiss_index_dir(self) -> Path:
        return self.cortex_dir / "faiss_index"

    @property
    def page_cache_path(self) -> Path:
        return self.cortex_dir / "page_cache.json"

    @property
    def env_path(self) -> Path:
        return self.cortex_dir / ".env"

    @classmethod
    def from_env(cls, repo_path: Path | None = None) -> Settings:
        """Load settings from .cortex/.env in the given or current directory."""
        repo = (repo_path or Path.cwd()).resolve()
        cortex_dir = repo / CORTEX_DIR_NAME
        env_file = cortex_dir / ".env"

        if env_file.exists():
            load_dotenv(env_file)

        # Detect old-format config and auto-migrate
        old_provider = os.getenv("LLM_PROVIDER")
        llm_model_raw = os.getenv("LLM_MODEL", "")

        if old_provider and "/" not in llm_model_raw:
            # v0.1 format: LLM_PROVIDER=google, LLM_MODEL=gemini-2.5-flash-lite
            # Migrate to v0.2 format: LLM_MODEL=google/gemini-2.5-flash-lite
            model_name = llm_model_raw or DEFAULT_MODELS.get(old_provider, "")
            llm_model = f"{old_provider}/{model_name}" if model_name else ""
            _migrate_env_file(env_file, old_provider, model_name, llm_model)
        elif llm_model_raw:
            llm_model = llm_model_raw
        else:
            llm_model = "gemini/gemini-2.5-flash-lite"

        return cls(
            llm_model=llm_model,
            llm_api_base=os.getenv("LLM_API_BASE") or None,
            llm_api_key=os.getenv("LLM_API_KEY") or None,
            llm_fallback=os.getenv("LLM_FALLBACK") or None,
            llm_model_code_analyzer=os.getenv("LLM_MODEL_CODE_ANALYZER") or None,
            llm_model_section_router=os.getenv("LLM_MODEL_SECTION_ROUTER") or None,
            llm_model_doc_writer=os.getenv("LLM_MODEL_DOC_WRITER") or None,
            llm_model_doc_validator=os.getenv("LLM_MODEL_DOC_VALIDATOR") or None,
            doc_output=os.getenv("DOC_OUTPUT", "local"),
            doc_sync=os.getenv("DOC_SYNC") or None,
            doc_detail_level=os.getenv("DOC_DETAIL_LEVEL", "standard"),
            doc_strategy=os.getenv("DOC_STRATEGY", "main-only"),
            doc_output_mode=os.getenv("DOC_OUTPUT_MODE", "apply"),
            doc_scope=os.getenv("DOC_SCOPE") or None,
            doc_scope_exclude=os.getenv("DOC_SCOPE_EXCLUDE") or None,
            doc_auto_sync=os.getenv("DOC_AUTO_SYNC", "").lower() in ("true", "1", "yes"),
            doc_sync_targets=os.getenv("DOC_SYNC_TARGETS", ""),
            mcp_server_enabled=os.getenv("MCP_SERVER_ENABLED", "").lower() in ("true", "1", "yes"),
            mcp_agent=os.getenv("MCP_AGENT", ""),
            # v0.1 compat
            llm_provider=old_provider or "",
            google_api_key=os.getenv("GOOGLE_API_KEY", ""),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            openrouter_api_key=os.getenv("OPENROUTER_API_KEY", ""),
            github_token=os.getenv("GITHUB_TOKEN", ""),
            repo_path=repo,
            cortex_dir=cortex_dir,
        )

    @property
    def is_initialized(self) -> bool:
        return self.env_path.exists()


def _migrate_env_file(
    env_file: Path,
    old_provider: str,
    old_model: str,
    new_model: str,
) -> None:
    """Migrate v0.1 .env to v0.2 format (backup first)."""
    if not env_file.exists():
        return

    try:
        backup = env_file.parent / ".env.bak"
        shutil.copy2(env_file, backup)

        content = env_file.read_text()
        # Remove LLM_PROVIDER line
        lines = [
            line for line in content.splitlines()
            if not line.strip().startswith("LLM_PROVIDER=")
        ]
        # Update LLM_MODEL to new format
        updated = []
        model_written = False
        for line in lines:
            if line.strip().startswith("LLM_MODEL="):
                updated.append(f"LLM_MODEL={new_model}")
                model_written = True
            else:
                updated.append(line)
        if not model_written:
            updated.append(f"LLM_MODEL={new_model}")

        env_file.write_text("\n".join(updated) + "\n")
        logger.info(
            f"Migrated .env from v0.1 format (provider={old_provider}, model={old_model}) "
            f"to v0.2 format (model={new_model}). Backup: {backup}"
        )
    except Exception as e:
        logger.warning(f"Failed to migrate .env: {e}")


def get_model_for_node(settings: Settings, node_name: str) -> str:
    """Return the LiteLLM model string for a given pipeline node.

    Checks for a per-node override first, falls back to the default model.
    """
    if node_name:
        override = getattr(settings, f"llm_model_{node_name}", None)
        if override:
            return override
    return settings.llm_model


# --- v0.1 compat: get_llm() ---
# Kept for backward compatibility during transition.
# Phase 4 will remove this once all agents use LiteLLM directly.


def get_llm(settings: Settings | None = None, model: str | None = None):
    """Create an LLM instance based on settings.

    DEPRECATED in v0.2 — agents should use _invoke_llm() with LiteLLM.
    Kept for backward compat during transition.
    """
    if settings is None:
        settings = Settings.from_env()

    # If using new v0.2 format (provider/model), extract provider
    llm_model = model or settings.llm_model
    if "/" in llm_model:
        provider, model_name = llm_model.split("/", 1)
    else:
        provider = settings.llm_provider or "google"
        model_name = llm_model or DEFAULT_MODELS.get(provider, "")

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=model_name,
            api_key=settings.anthropic_api_key or settings.llm_api_key,
        )

    if provider == "openrouter":
        from langchain_openai import ChatOpenAI

        if not model_name:
            raise ValueError(
                "LLM_MODEL is required for OpenRouter. "
                "Set it in .cortex/.env (e.g. LLM_MODEL=openrouter/anthropic/claude-sonnet-4)"
            )

        return ChatOpenAI(
            model=model_name,
            api_key=settings.openrouter_api_key or settings.llm_api_key,
            base_url="https://openrouter.ai/api/v1",
        )

    # Default: Google Gemini
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(
        model=model_name or DEFAULT_MODELS["google"],
        google_api_key=settings.google_api_key,
    )
