"""Configuration and LLM factory for Codebase Cortex."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.language_models import BaseChatModel

CORTEX_DIR_NAME = ".cortex"


def find_cortex_dir(start: Path | None = None) -> Path:
    """Find the .cortex directory, starting from the given path or cwd.

    Returns the .cortex path (may not exist yet — for `cortex init`).
    """
    start = start or Path.cwd()
    return start.resolve() / CORTEX_DIR_NAME


DEFAULT_MODELS: dict[str, str] = {
    "google": "gemini-2.5-flash-lite",
    "anthropic": "claude-sonnet-4-20250514",
    "openrouter": "",  # no sensible default — user must choose
}

RECOMMENDED_MODELS: dict[str, list[str]] = {
    "google": [
        "gemini-2.5-flash-lite",
        "gemini-3-flash-preview",
        "gemini-2.5-pro",
    ],
    "anthropic": [
        "claude-sonnet-4-20250514",
        "claude-haiku-4-5-20251001",
    ],
    "openrouter": [
        "anthropic/claude-sonnet-4",
        "google/gemini-2.5-flash-lite",
        "google/gemini-3-flash-preview",
    ],
}


@dataclass
class Settings:
    """Application settings loaded from .cortex/.env in the target repo."""

    llm_provider: str = "google"
    llm_model: str = ""
    google_api_key: str = ""
    anthropic_api_key: str = ""
    openrouter_api_key: str = ""
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

        provider = os.getenv("LLM_PROVIDER", "google")
        return cls(
            llm_provider=provider,
            llm_model=os.getenv("LLM_MODEL", DEFAULT_MODELS.get(provider, "")),
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


def get_llm(settings: Settings | None = None, model: str | None = None) -> BaseChatModel:
    """Create an LLM instance based on settings.

    Args:
        settings: Application settings. Loads from env if not provided.
        model: Override model name. Uses LLM_MODEL from env, then provider default.
    """
    if settings is None:
        settings = Settings.from_env()

    resolved_model = model or settings.llm_model

    if settings.llm_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=resolved_model or DEFAULT_MODELS["anthropic"],
            api_key=settings.anthropic_api_key,
        )

    if settings.llm_provider == "openrouter":
        from langchain_openai import ChatOpenAI

        if not resolved_model:
            raise ValueError(
                "LLM_MODEL is required for OpenRouter. "
                "Set it in .cortex/.env (e.g. LLM_MODEL=anthropic/claude-sonnet-4)"
            )

        return ChatOpenAI(
            model=resolved_model,
            api_key=settings.openrouter_api_key,
            base_url="https://openrouter.ai/api/v1",
        )

    # Default: Google Gemini
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(
        model=resolved_model or DEFAULT_MODELS["google"],
        google_api_key=settings.google_api_key,
    )
