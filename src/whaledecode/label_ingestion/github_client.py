"""Async GitHub API client: rate-limited, retrying, PAT-aware, no full clone."""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
DEFAULT_PER_PAGE = 100
MAX_RETRIES = 4
BACKOFF_BASE = 1.5


class GitHubError(RuntimeError):
    """Raised for non-retryable GitHub API failures (4xx other than 403/429)."""


@dataclass
class RateLimiter:
    """Cooperative rate limiter: min spacing + adaptive pause on quota exhaustion.

    GitHub's authenticated quota is 5000 req/hour; we keep a small headroom and
    honor ``X-RateLimit-Remaining`` / ``X-RateLimit-Reset`` returned by the API.
    """

    min_interval: float = 0.05  # <= 1200 req/min headroom under the 5000/hr cap
    _lock: asyncio.Lock = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self._lock = asyncio.Lock()
        self._last_call = 0.0
        self._paused_until = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = max(self.min_interval, self._paused_until - now)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call = time.monotonic()

    def update_from_response(self, headers: httpx.Headers) -> None:
        remaining = headers.get("X-RateLimit-Remaining")
        reset = headers.get("X-RateLimit-Reset")
        if remaining is not None and int(remaining) <= 1 and reset is not None:
            # Pause until the quota resets (with 2s grace).
            self._paused_until = max(self._paused_until, float(reset) - time.time() + 2.0)


class GitHubClient:
    """Streams repository trees + raw blobs via the GitHub REST API (no git clone)."""

    def __init__(
        self,
        token: str | None = None,
        *,
        timeout: float = 30.0,
        max_retries: int = MAX_RETRIES,
        limiter: RateLimiter | None = None,
    ) -> None:
        self._token = token or os.getenv("GITHUB_TOKEN")
        self._max_retries = max_retries
        self._limiter = limiter or RateLimiter()
        self._client = httpx.AsyncClient(
            base_url=GITHUB_API,
            timeout=timeout,
            headers=self._headers(),
            follow_redirects=True,
        )

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> GitHubClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def _request(self, method: str, url: str, **kw: Any) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            await self._limiter.acquire()
            try:
                resp = await self._client.request(method, url, **kw)
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = exc
                await self._backoff(attempt, f"transport: {exc}")
                continue

            self._limiter.update_from_response(resp.headers)
            if resp.status_code in (429, 403) and "rate limit" in resp.text.lower():
                await self._backoff(attempt, f"rate limited (HTTP {resp.status_code})")
                continue
            if resp.status_code >= 500:
                last_exc = GitHubError(f"HTTP {resp.status_code}")
                await self._backoff(attempt, f"server error (HTTP {resp.status_code})")
                continue
            if resp.status_code >= 400:
                raise GitHubError(f"HTTP {resp.status_code} {method} {url}: {resp.text[:200]}")
            return resp
        raise GitHubError(f"exhausted retries for {method} {url}: {last_exc}")

    async def _backoff(self, attempt: int, reason: str) -> None:
        delay = BACKOFF_BASE * (2**attempt)
        logger.warning("github_retry", extra={"attempt": attempt, "reason": reason, "delay": delay})
        await asyncio.sleep(delay)

    async def default_branch(self, full_name: str) -> str:
        resp = await self._request("GET", f"/repos/{full_name}")
        return resp.json().get("default_branch", "main")

    async def fetch_tree(self, full_name: str, ref: str | None = None) -> list[dict[str, Any]]:
        """Return all blob entries from a repository tree (recursive)."""
        if ref is None:
            ref = await self.default_branch(full_name)
        resp = await self._request(
            "GET", f"/repos/{full_name}/git/trees/{ref}", params={"recursive": "1"}
        )
        data = resp.json()
        if data.get("truncated"):
            logger.warning("github_tree_truncated", extra={"repo": full_name})
        return [e for e in data.get("tree", []) if e.get("type") == "blob"]

    async def fetch_blob_text(self, full_name: str, sha: str) -> str:
        """Fetch a blob's decoded text content via the blobs API (base64)."""
        resp = await self._request("GET", f"/repos/{full_name}/git/blobs/{sha}")
        blob = resp.json()
        content = blob.get("content", "")
        if blob.get("encoding") == "base64":
            return base64.b64decode(content).decode("utf-8", errors="replace")
        return content

    async def iter_label_files(
        self, full_name: str, ref: str | None, suffixes: frozenset[str], path_includes: tuple[str, ...]
    ) -> AsyncIterator[tuple[str, str]]:
        """Yield ``(path, text)`` for every label-looking file in the repo tree."""
        tree = await self.fetch_tree(full_name, ref)
        for entry in tree:
            path: str = entry.get("path", "")
            if not path.lower().endswith(tuple(suffixes)):
                continue
            if path_includes and not any(inc in path for inc in path_includes):
                continue
            try:
                text = await self.fetch_blob_text(full_name, entry["sha"])
            except GitHubError as exc:
                logger.warning("github_blob_skip", extra={"path": path, "error": str(exc)})
                continue
            yield path, text
