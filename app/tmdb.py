"""Small synchronous TMDB v3 client with a per-process TTL response cache."""
from __future__ import annotations

import time
from typing import Any

import httpx


class TMDBError(RuntimeError):
    """A network, HTTP, or response error from TMDB."""


class TMDBClient:
    """Fetch TMDB API data without exposing credentials to the frontend."""

    BASE_URL = "https://api.themoviedb.org/3"

    def __init__(self, api_key: str | None, ttl_seconds: int = 3600, timeout_seconds: float = 8.0):
        self.api_key = (api_key or "").strip()
        self.ttl_seconds = ttl_seconds
        self.timeout_seconds = timeout_seconds
        self._cache: dict[tuple[str, tuple[tuple[str, str], ...]], tuple[float, dict[str, Any]]] = {}
        self._client = httpx.Client(timeout=timeout_seconds, follow_redirects=True)

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def close(self) -> None:
        self._client.close()

    def get(self, path: str, *, append_details: bool = False) -> dict[str, Any]:
        """Get and cache a JSON object; raise TMDBError on failed requests."""
        if not self.enabled:
            raise TMDBError("TMDB_API_KEY is not configured.")
        if not path.startswith("/") or ".." in path:
            raise ValueError("TMDB paths must be API-relative paths.")
        params = {"api_key": self.api_key}
        if append_details and path.startswith("/movie/") and path.count("/") == 2 and path.rsplit("/", 1)[-1].isdigit():
            params["append_to_response"] = "credits,videos,release_dates"
        key = (path, tuple(sorted((name, str(value)) for name, value in params.items())))
        now = time.monotonic()
        cached = self._cache.get(key)
        if cached and cached[0] > now:
            return cached[1]
        if cached:
            self._cache.pop(key, None)
        try:
            response = self._client.get(f"{self.BASE_URL}{path}", params=params)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise TMDBError("TMDB returned an invalid response.")
        except (httpx.HTTPError, ValueError) as exc:
            raise TMDBError("TMDB is unavailable right now.") from exc
        self._cache[key] = (now + self.ttl_seconds, payload)
        return payload

