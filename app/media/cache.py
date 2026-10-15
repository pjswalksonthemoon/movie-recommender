"""Reusable in-process TTL cache and bounded asynchronous HTTP provider."""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx


class ProviderError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class TTLCache:
    """Small swap-friendly cache interface: get/set with a per-entry lifetime."""

    def __init__(self):
        self._values: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        entry = self._values.get(key)
        if not entry:
            return None
        if entry[0] <= time.monotonic():
            self._values.pop(key, None)
            return None
        return entry[1]

    def set(self, key: str, value: Any, ttl: int) -> None:
        self._values[key] = (time.monotonic() + ttl, value)


class AsyncProvider:
    """Shared timeouts, retries, semaphore and short/long cache policy."""

    def __init__(self, base_url: str, *, client: httpx.AsyncClient | None = None,
                 cache: TTLCache | None = None, min_interval: float = 0):
        self.client = client or httpx.AsyncClient(base_url=base_url, timeout=httpx.Timeout(8.0),
                                                   follow_redirects=True)
        self._owns_client = client is None
        self.cache = cache or TTLCache()
        self.semaphore = asyncio.Semaphore(8)
        self.min_interval = min_interval
        self._pace_lock = asyncio.Lock()
        self._next_at = 0.0

    async def close(self):
        if self._owns_client:
            await self.client.aclose()

    async def _pace(self):
        if not self.min_interval:
            return
        async with self._pace_lock:
            delay = self._next_at - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            self._next_at = time.monotonic() + self.min_interval

    async def request(self, method: str, path: str, *, params: dict | None = None,
                      body: dict | None = None, ttl: int = 600) -> dict:
        key = json.dumps([method, path, params, body], sort_keys=True, default=str)
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        for attempt in range(3):
            await self._pace()
            try:
                async with self.semaphore:
                    response = await self.client.request(method, path, params=params, json=body)
            except httpx.HTTPError as exc:
                if attempt == 2:
                    raise ProviderError("Media provider is unavailable.") from exc
                await asyncio.sleep(0.25 * 2**attempt)
                continue
            remaining = response.headers.get("X-RateLimit-Remaining")
            reset = response.headers.get("X-RateLimit-Reset")
            if remaining == "0" and reset:
                try:
                    self._next_at = max(self._next_at, time.monotonic() + max(0, float(reset) - time.time()))
                except ValueError:
                    pass
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < 2:
                    try:
                        retry_after = float(response.headers.get("Retry-After", "0"))
                    except ValueError:
                        retry_after = 0
                    await asyncio.sleep(min(60, max(retry_after, 0.25 * 2**attempt)))
                    continue
            try:
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("Expected a JSON object.")
            except (httpx.HTTPError, ValueError) as exc:
                raise ProviderError("Media provider returned an error.", response.status_code) from exc
            self.cache.set(key, payload, ttl)
            return payload
        raise ProviderError("Media provider is unavailable.")
