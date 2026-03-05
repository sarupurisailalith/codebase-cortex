"""Persist and manage OAuth tokens for Notion MCP."""

from __future__ import annotations

import json
import time
from pathlib import Path
from dataclasses import dataclass

from codebase_cortex.auth.oauth import refresh_access_token


@dataclass
class TokenData:
    """Stored OAuth token data."""

    access_token: str
    refresh_token: str
    expires_at: float
    client_id: str
    client_secret: str
    token_endpoint: str | None = None

    @property
    def is_expired(self) -> bool:
        return time.time() >= self.expires_at - 60  # 60s buffer

    def to_dict(self) -> dict:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "token_endpoint": self.token_endpoint,
        }

    @classmethod
    def from_dict(cls, data: dict) -> TokenData:
        return cls(**data)


def save_tokens(token_data: TokenData, path: Path) -> None:
    """Save token data to a JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(token_data.to_dict(), indent=2))


def load_tokens(path: Path) -> TokenData | None:
    """Load token data from a JSON file, or None if not found."""
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    return TokenData.from_dict(data)


async def get_valid_token(path: Path) -> str:
    """Get a valid access token, refreshing if expired.

    Args:
        path: Path to the token JSON file.

    Returns:
        A valid access token string.

    Raises:
        FileNotFoundError: If no tokens are stored.
        RuntimeError: If refresh fails.
    """
    token_data = load_tokens(path)
    if token_data is None:
        raise FileNotFoundError(f"No tokens found at {path}. Run 'cortex init' first.")

    if not token_data.is_expired:
        return token_data.access_token

    result = await refresh_access_token(
        refresh_token=token_data.refresh_token,
        client_id=token_data.client_id,
        client_secret=token_data.client_secret,
        token_endpoint=token_data.token_endpoint,
    )

    token_data.access_token = result["access_token"]
    if "refresh_token" in result:
        token_data.refresh_token = result["refresh_token"]
    token_data.expires_at = time.time() + result.get("expires_in", 3600)
    save_tokens(token_data, path)

    return token_data.access_token
