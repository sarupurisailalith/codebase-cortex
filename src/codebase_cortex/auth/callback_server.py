"""Local HTTP callback server for OAuth authorization code receipt."""

from __future__ import annotations

import asyncio
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from threading import Thread


class _CallbackHandler(BaseHTTPRequestHandler):
    """Handles the OAuth callback and extracts the authorization code."""

    code: str | None = None
    state: str | None = None
    error: str | None = None

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if "error" in params:
            _CallbackHandler.error = params["error"][0]
            self._respond("Authorization failed. You can close this tab.")
        elif "code" in params:
            _CallbackHandler.code = params["code"][0]
            _CallbackHandler.state = params.get("state", [None])[0]
            self._respond("Authorization successful! You can close this tab.")
        else:
            self._respond("Unexpected callback. You can close this tab.", status=400)

    def _respond(self, message: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        html = f"<html><body><h2>{message}</h2></body></html>"
        self.wfile.write(html.encode())

    def log_message(self, format: str, *args: object) -> None:
        pass  # Suppress request logging


async def wait_for_callback(
    port: int = 9876,
    timeout: float = 120.0,
) -> tuple[str, str | None]:
    """Start a local HTTP server and wait for the OAuth callback.

    Args:
        port: Port to listen on.
        timeout: Maximum seconds to wait for the callback.

    Returns:
        Tuple of (authorization_code, state).

    Raises:
        TimeoutError: If no callback received within timeout.
        RuntimeError: If the authorization was denied or failed.
    """
    _CallbackHandler.code = None
    _CallbackHandler.state = None
    _CallbackHandler.error = None

    server = HTTPServer(("localhost", port), _CallbackHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        elapsed = 0.0
        interval = 0.5
        while elapsed < timeout:
            if _CallbackHandler.code is not None:
                return _CallbackHandler.code, _CallbackHandler.state
            if _CallbackHandler.error is not None:
                raise RuntimeError(f"OAuth error: {_CallbackHandler.error}")
            await asyncio.sleep(interval)
            elapsed += interval
        raise TimeoutError("OAuth callback timed out")
    finally:
        server.shutdown()
