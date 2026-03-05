"""OAuth 2.0 + PKCE flow for Notion MCP authorization."""

from __future__ import annotations

import base64
import hashlib
import secrets
import webbrowser

import httpx

NOTION_MCP_METADATA_URL = "https://mcp.notion.com/.well-known/oauth-authorization-server"

# Fallback URLs (prefer metadata-discovered endpoints)
NOTION_AUTH_URL = "https://mcp.notion.com/authorize"
NOTION_TOKEN_URL = "https://mcp.notion.com/token"
NOTION_CLIENT_REGISTRATION_URL = "https://mcp.notion.com/register"


def generate_pkce_pair() -> tuple[str, str]:
    """Generate a PKCE code verifier and challenge (S256).

    Returns:
        Tuple of (code_verifier, code_challenge).
    """
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


async def fetch_oauth_metadata() -> dict:
    """Fetch the OAuth authorization server metadata from Notion MCP."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(NOTION_MCP_METADATA_URL)
        resp.raise_for_status()
        return resp.json()


async def register_client(
    redirect_uri: str,
    registration_endpoint: str | None = None,
) -> dict:
    """Dynamically register an OAuth client with Notion MCP.

    Args:
        redirect_uri: The callback URI (e.g., http://localhost:9876/callback).
        registration_endpoint: Override registration endpoint URL.

    Returns:
        Client registration response with client_id and client_secret.
    """
    endpoint = registration_endpoint or NOTION_CLIENT_REGISTRATION_URL
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            endpoint,
            json={
                "client_name": "Codebase Cortex",
                "redirect_uris": [redirect_uri],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "client_secret_post",
            },
        )
        resp.raise_for_status()
        return resp.json()


def build_authorization_url(
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    state: str,
    authorization_endpoint: str | None = None,
) -> str:
    """Build the Notion OAuth authorization URL.

    Args:
        client_id: The registered client ID.
        redirect_uri: Callback URI.
        code_challenge: PKCE S256 challenge.
        state: Random state for CSRF protection.
        authorization_endpoint: Override auth endpoint URL.

    Returns:
        The full authorization URL to open in a browser.
    """
    endpoint = authorization_endpoint or NOTION_AUTH_URL
    params = httpx.QueryParams(
        client_id=client_id,
        redirect_uri=redirect_uri,
        response_type="code",
        code_challenge=code_challenge,
        code_challenge_method="S256",
        state=state,
        owner="user",
    )
    return f"{endpoint}?{params}"


async def exchange_code(
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    code_verifier: str,
    token_endpoint: str | None = None,
) -> dict:
    """Exchange authorization code for access and refresh tokens.

    Args:
        code: The authorization code from the callback.
        client_id: Registered client ID.
        client_secret: Registered client secret.
        redirect_uri: The same redirect URI used in authorization.
        code_verifier: The PKCE code verifier.
        token_endpoint: Override token endpoint URL.

    Returns:
        Token response with access_token, refresh_token, expires_in.
    """
    endpoint = token_endpoint or NOTION_TOKEN_URL
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            endpoint,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "client_secret": client_secret,
                "code_verifier": code_verifier,
            },
        )
        resp.raise_for_status()
        return resp.json()


async def refresh_access_token(
    refresh_token: str,
    client_id: str,
    client_secret: str,
    token_endpoint: str | None = None,
) -> dict:
    """Refresh an expired access token.

    Args:
        refresh_token: The refresh token.
        client_id: Registered client ID.
        client_secret: Registered client secret.
        token_endpoint: Override token endpoint URL.

    Returns:
        New token response with access_token and possibly new refresh_token.
    """
    endpoint = token_endpoint or NOTION_TOKEN_URL
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            endpoint,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
            },
        )
        resp.raise_for_status()
        return resp.json()


def open_browser(url: str) -> None:
    """Open the authorization URL in the user's browser."""
    webbrowser.open(url)
