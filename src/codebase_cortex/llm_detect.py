"""Auto-detection of available LLM providers.

Used by `cortex init --quick` (Phase 6) and can be used
by Settings for smart defaults.
"""

from __future__ import annotations

import os


def detect_available_models() -> list[dict]:
    """Check for available LLM providers. Returns list sorted by preference.

    Prefers local models (Ollama) over cloud providers for privacy.
    Among cloud providers, prefers cheapest first.

    Returns:
        List of dicts with keys: model (LiteLLM format), local (bool).
    """
    available: list[dict] = []

    # 1. Check for local Ollama server (preferred — code stays local)
    try:
        import httpx

        resp = httpx.get("http://localhost:11434/api/tags", timeout=2.0)
        if resp.status_code == 200:
            models = resp.json().get("models", [])
            for m in models:
                available.append({"model": f"ollama/{m['name']}", "local": True})
    except Exception:
        pass

    # 2. Check for cloud API keys in environment (cheapest first)
    env_map = [
        ("GOOGLE_API_KEY", "google/gemini-2.5-flash-lite"),
        ("ANTHROPIC_API_KEY", "anthropic/claude-haiku-4-5-20251001"),
        ("OPENAI_API_KEY", "openai/gpt-4o-mini"),
        ("OPENROUTER_API_KEY", "openrouter/auto"),
    ]
    for env_var, model in env_map:
        if os.environ.get(env_var):
            available.append({"model": model, "local": False})

    return available


def best_available_model() -> str | None:
    """Return the best available model string, or None if none found."""
    models = detect_available_models()
    return models[0]["model"] if models else None
