"""Configuration and LLM factory for Codebase Cortex."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.language_models import BaseChatModel


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"


@dataclass
class Settings:
    """Application settings loaded from environment."""

    llm_provider: str = "google"
    google_api_key: str = ""
    anthropic_api_key: str = ""
    github_token: str = ""
    repo_path: str = "."
    data_dir: Path = field(default_factory=lambda: DATA_DIR)
    notion_token_path: Path = field(default_factory=lambda: DATA_DIR / "notion_tokens.json")
    oauth_callback_port: int = 9876

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv(PROJECT_ROOT / ".env")
        return cls(
            llm_provider=os.getenv("LLM_PROVIDER", "google"),
            google_api_key=os.getenv("GOOGLE_API_KEY", ""),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            github_token=os.getenv("GITHUB_TOKEN", ""),
            repo_path=os.getenv("REPO_PATH", "."),
        )


def get_llm(settings: Settings | None = None, model: str | None = None) -> BaseChatModel:
    """Create an LLM instance based on settings.

    Args:
        settings: Application settings. Loads from env if not provided.
        model: Override model name. Defaults based on provider.
    """
    if settings is None:
        settings = Settings.from_env()

    if settings.llm_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=model or "claude-sonnet-4-20250514",
            api_key=settings.anthropic_api_key,
        )

    # Default: Google Gemini
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(
        model=model or "gemini-2.0-flash",
        google_api_key=settings.google_api_key,
    )
