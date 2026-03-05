"""Async token bucket rate limiter for Notion MCP API calls."""

from __future__ import annotations

import asyncio
import time


class TokenBucket:
    """Token bucket rate limiter.

    Args:
        rate: Number of tokens added per second.
        capacity: Maximum tokens in the bucket.
    """

    def __init__(self, rate: float, capacity: int) -> None:
        self.rate = rate
        self.capacity = capacity
        self._tokens = float(capacity)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
        self._last_refill = now

    async def acquire(self, tokens: int = 1) -> None:
        """Wait until the requested number of tokens are available."""
        async with self._lock:
            while True:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                wait = (tokens - self._tokens) / self.rate
                await asyncio.sleep(wait)


class NotionRateLimiter:
    """Dual token bucket for Notion MCP rate limits.

    - General: 180 requests/minute (3/sec)
    - Search: 30 requests/minute (0.5/sec)
    """

    def __init__(self) -> None:
        self.general = TokenBucket(rate=3.0, capacity=180)
        self.search = TokenBucket(rate=0.5, capacity=30)

    async def acquire(self, is_search: bool = False) -> None:
        await self.general.acquire()
        if is_search:
            await self.search.acquire()
