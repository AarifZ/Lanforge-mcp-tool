"""Async HTTP/HTTPS client for the LANforge GUI JSON API.

Handles session acquisition (``POST /newsession`` -> ``X-LFJson-Session``
header), connection pooling, retries with exponential backoff, and structured
error translation. One instance per LANforge system.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from ..errors import LFConnectionError, QueryError
from ..models import SystemConfig

logger = logging.getLogger(__name__)

SESSION_HEADER = "X-LFJson-Session"

#: Status codes worth retrying (transient GUI hiccups).
RETRYABLE_STATUS = {502, 503, 504}


class LFHttpClient:
    def __init__(self, system: SystemConfig, transport: httpx.AsyncBaseTransport | None = None):
        self.system = system
        self._session_id: str | None = None
        self._session_lock = asyncio.Lock()
        self._client = httpx.AsyncClient(
            base_url=system.base_url,
            timeout=httpx.Timeout(system.timeout_sec, connect=system.connect_timeout_sec),
            verify=system.verify_ssl if system.protocol == "https" else False,
            auth=(system.username, system.password) if system.protocol == "https" else None,
            headers={"Accept": "application/json"},
            transport=transport,
        )

    @property
    def session_id(self) -> str | None:
        return self._session_id

    async def close(self) -> None:
        await self._client.aclose()

    async def ensure_session(self) -> str:
        """Acquire (once) the LANforge JSON session id."""
        if self._session_id:
            return self._session_id
        async with self._session_lock:
            if self._session_id:
                return self._session_id
            try:
                resp = await self._client.post("/newsession")
            except httpx.HTTPError as exc:
                raise LFConnectionError(
                    f"Cannot reach LANforge GUI at {self.system.base_url}: {exc}",
                    details={"system": self.system.id},
                ) from exc
            session = resp.headers.get(SESSION_HEADER)
            if not session:
                # Older GUIs may not issue sessions; operate without one.
                logger.warning("%s: /newsession returned no %s header", self.system.id, SESSION_HEADER)
                self._session_id = ""
            else:
                self._session_id = session
            return self._session_id

    def _headers(self) -> dict[str, str]:
        headers = {}
        if self._session_id:
            headers[SESSION_HEADER] = self._session_id
        return headers

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Issue a request with session, retry and reconnect handling."""
        await self.ensure_session()
        last_exc: Exception | None = None
        for attempt in range(self.system.retries + 1):
            try:
                resp = await self._client.request(method, url, headers=self._headers(), **kwargs)
                if resp.status_code in RETRYABLE_STATUS and attempt < self.system.retries:
                    await asyncio.sleep(self.system.retry_backoff_sec * (2**attempt))
                    continue
                if resp.status_code == 401 and attempt == 0:
                    # Session may have expired: drop it and re-acquire once.
                    self._session_id = None
                    await self.ensure_session()
                    continue
                return resp
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt < self.system.retries:
                    await asyncio.sleep(self.system.retry_backoff_sec * (2**attempt))
                    continue
        raise LFConnectionError(
            f"LANforge GUI at {self.system.base_url} unreachable after "
            f"{self.system.retries + 1} attempts: {last_exc}",
            details={"system": self.system.id, "url": url},
        )

    async def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        resp = await self._request("GET", url, params=params)
        if resp.status_code == 404:
            raise QueryError(
                f"Endpoint {url} returned 404 (not found on this LANforge).",
                details={"url": url, "system": self.system.id},
            )
        if resp.status_code >= 400:
            raise QueryError(
                f"GET {url} failed with HTTP {resp.status_code}: {resp.text[:500]}",
                details={"url": url, "status": resp.status_code},
            )
        try:
            return resp.json()
        except ValueError as exc:
            raise QueryError(
                f"GET {url} returned non-JSON content (is this really a LANforge GUI port?)",
                details={"url": url, "content_type": resp.headers.get("content-type", "")},
            ) from exc

    async def post_json(self, url: str, data: dict[str, Any]) -> tuple[int, Any]:
        """POST JSON; returns (status_code, parsed body or text)."""
        resp = await self._request("POST", url, json=data)
        body: Any
        try:
            body = resp.json()
        except ValueError:
            body = resp.text
        return resp.status_code, body

    async def get_text(self, url: str) -> str:
        resp = await self._request("GET", url)
        return resp.text
