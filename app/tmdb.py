"""TMDB v3 access and compact, cached movie card summaries."""
from __future__ import annotations

import asyncio
import re
import time
from typing import Any

import httpx

IMAGE_ROOT = "https://image.tmdb.org/t/p/"


class TMDBError(RuntimeError):
    """A network, HTTP, or response error from TMDB."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def image_url(path: Any, size: str) -> str | None:
    """Turn a TMDB image path into an absolute URL, ignoring invalid values."""
    return f"{IMAGE_ROOT}{size}{path}" if isinstance(path, str) and path.startswith("/") else None


def short_overview(value: Any, limit: int = 140) -> str:
    """Trim an overview at a word boundary without splitting a word."""
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    prefix = text[:limit + 1]
    cut = prefix.rfind(" ")
    return (prefix[:cut] if cut > 0 else text[:limit]).rstrip(" ,.;:") + "…"


def basic_card(movie_id: int, title: str, genres: str | list[str]) -> dict[str, Any]:
    """MovieLens fallback for a card when TMDB is unavailable."""
    year = re.search(r"\((\d{4})\)\s*$", title)
    genre_list = genres if isinstance(genres, list) else genres.split("|")
    return {
        "movie_id": movie_id, "title": title, "year": year.group(1) if year else None,
        "genres": [genre for genre in genre_list if genre and genre != "(no genres listed)"],
        "poster_url": None, "summary": "", "rating": None,
        "director": None, "cast": [],
    }


def build_card_summary(payload: dict[str, Any], basic: dict[str, Any]) -> dict[str, Any]:
    """Reduce an appended TMDB movie response to the fields needed by cards."""
    credits = payload.get("credits") or {}
    credits = credits if isinstance(credits, dict) else {}
    crew = credits.get("crew") or []
    cast = credits.get("cast") or []
    crew = crew if isinstance(crew, list) else []
    cast = cast if isinstance(cast, list) else []
    director = next(({"id": person["id"], "name": person["name"]} for person in crew
                     if isinstance(person, dict) and person.get("job") == "Director"
                     and isinstance(person.get("id"), int) and person.get("name")), None)
    stars = [{"id": person["id"], "name": person["name"]} for person in cast
             if isinstance(person, dict) and isinstance(person.get("id"), int) and person.get("name")][:3]
    release_date = payload.get("release_date") or ""
    genres = [item["name"] for item in payload.get("genres") or []
              if isinstance(item, dict) and item.get("name")]
    vote = payload.get("vote_average")
    return {
        **basic,
        "title": payload.get("title") or basic["title"],
        "year": release_date[:4] if isinstance(release_date, str) and release_date[:4].isdigit() else basic["year"],
        "genres": genres or basic["genres"],
        "poster_url": image_url(payload.get("poster_path"), "w342"),
        "summary": short_overview(payload.get("overview")),
        "rating": round(float(vote) * 10) if isinstance(vote, (int, float)) else None,
        "director": director, "cast": stars,
    }


class TMDBClient:
    """Fetch TMDB data server-side, with one-hour response and card caches."""

    BASE_URL = "https://api.themoviedb.org/3"

    def __init__(self, api_key: str | None, ttl_seconds: int = 3600, timeout_seconds: float = 8.0):
        self.api_key = (api_key or "").strip()
        self.ttl_seconds = ttl_seconds
        self.timeout_seconds = timeout_seconds
        self._cache: dict[tuple[str, tuple[tuple[str, str], ...]], tuple[float, dict[str, Any]]] = {}
        self._card_cache: dict[int, tuple[float, dict[str, Any]]] = {}
        self._client = httpx.Client(timeout=timeout_seconds, follow_redirects=True)
        self._async_client = httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True)
        self._semaphore = asyncio.Semaphore(8)

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def close(self) -> None:
        self._client.close()

    async def aclose(self) -> None:
        await self._async_client.aclose()

    def _request_parts(self, path: str, append: str | None):
        if not self.enabled:
            raise TMDBError("TMDB_API_KEY is not configured.")
        if not path.startswith("/") or ".." in path:
            raise ValueError("TMDB paths must be API-relative paths.")
        params = {"api_key": self.api_key}
        if append:
            params["append_to_response"] = append
        return params, (path, tuple(sorted(params.items())))

    def get(self, path: str, *, append_details: bool = False, append_to_response: str | None = None) -> dict[str, Any]:
        """Get and cache a JSON object; raise TMDBError on failed requests."""
        append = append_to_response or ("credits,videos,release_dates" if append_details else None)
        params, key = self._request_parts(path, append)
        cached = self._cache.get(key)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        try:
            response = self._client.get(f"{self.BASE_URL}{path}", params=params)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise TMDBError("TMDB returned an invalid response.")
        except httpx.HTTPStatusError as exc:
            raise TMDBError("TMDB returned an error.", exc.response.status_code) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise TMDBError("TMDB is unavailable right now.") from exc
        self._cache[key] = (time.monotonic() + self.ttl_seconds, payload)
        return payload

    async def aget(self, path: str, *, append_to_response: str | None = None) -> dict[str, Any]:
        """Async GET for concurrent card enrichment, using the same response cache."""
        params, key = self._request_parts(path, append_to_response)
        cached = self._cache.get(key)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        try:
            async with self._semaphore:
                response = await self._async_client.get(f"{self.BASE_URL}{path}", params=params)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise TMDBError("TMDB returned an invalid response.")
        except httpx.HTTPStatusError as exc:
            raise TMDBError("TMDB returned an error.", exc.response.status_code) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise TMDBError("TMDB is unavailable right now.") from exc
        self._cache[key] = (time.monotonic() + self.ttl_seconds, payload)
        return payload

    async def card_summary(self, tmdb_id: int | None, basic: dict[str, Any]) -> dict[str, Any]:
        """Return a cached TMDB card, or its MovieLens fallback on any TMDB error."""
        movie_id = basic["movie_id"]
        cached = self._card_cache.get(movie_id)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        if not self.enabled or not tmdb_id:
            return basic
        try:
            payload = await self.aget(f"/movie/{tmdb_id}", append_to_response="credits")
            result = build_card_summary(payload, basic)
            self._card_cache[movie_id] = (time.monotonic() + self.ttl_seconds, result)
            return result
        except TMDBError:
            return basic
