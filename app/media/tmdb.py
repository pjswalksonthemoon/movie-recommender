"""TMDB movie and TV search, browse, details and recommendations."""
from __future__ import annotations

import asyncio
from typing import Any

from .cache import AsyncProvider, ProviderError
from .models import Credit, Media, Season
from ..tmdb import image_url, short_overview

GENRES = {
    "Action": {"movie": 28, "tv": 10759}, "Comedy": {"movie": 35, "tv": 35},
    "Drama": {"movie": 18, "tv": 18}, "Sci-Fi": {"movie": 878, "tv": 10765},
    "Fantasy": {"movie": 14, "tv": 10765},
    "Adventure": {"movie": 12, "tv": 10759},
    "Horror": {"movie": 27, "tv": 9648},
    "Mystery": {"movie": 9648, "tv": 9648},
    "Romance": {"movie": 10749, "tv": 18},
    "Thriller": {"movie": 53, "tv": 80},
}


def _year(value: Any) -> str | None:
    return value[:4] if isinstance(value, str) and value[:4].isdigit() else None


def _credits(payload: dict, media_type: str) -> tuple[list[Credit], list[Credit]]:
    credits = payload.get("credits") or {}
    if not isinstance(credits, dict):
        credits = {}
    cast = [Credit(id=person.get("id"), name=person.get("name") or "Unknown",
                   character=person.get("character"), photo_url=image_url(person.get("profile_path"), "w185"))
            for person in (credits.get("cast") or [])[:12] if isinstance(person, dict)]
    if media_type == "tv":
        creators = [Credit(id=person.get("id"), name=person["name"],
                           photo_url=image_url(person.get("profile_path"), "w185"))
                    for person in payload.get("created_by") or [] if isinstance(person, dict) and person.get("name")]
    else:
        creators = [Credit(id=person.get("id"), name=person["name"])
                    for person in credits.get("crew") or []
                    if isinstance(person, dict) and person.get("job") == "Director" and person.get("name")]
    return creators, cast


def _trailer(payload: dict) -> str | None:
    videos = (payload.get("videos") or {}).get("results") or []
    trailer = next((video for video in videos if isinstance(video, dict) and
                    video.get("site") == "YouTube" and video.get("type") == "Trailer"), None)
    return trailer.get("key") if trailer else None


def _certification(payload: dict, media_type: str) -> str | None:
    key = "release_dates" if media_type == "movie" else "content_ratings"
    countries = (payload.get(key) or {}).get("results") or []
    preferred = sorted((item for item in countries if isinstance(item, dict)),
                       key=lambda item: item.get("iso_3166_1") != "US")
    for country in preferred:
        if media_type == "tv" and country.get("rating"):
            return country["rating"]
        for release in country.get("release_dates") or []:
            if release.get("certification"):
                return release["certification"]
    return None


class TMDBProvider(AsyncProvider):
    def __init__(self, api_key: str | None, **kwargs):
        super().__init__("https://api.themoviedb.org/3", **kwargs)
        self.api_key = (api_key or "").strip()

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def _get(self, path: str, params: dict | None = None, ttl: int = 600) -> dict:
        if not self.enabled:
            raise ProviderError("TMDB_API_KEY is not configured.")
        return await self.request("GET", path, params={"api_key": self.api_key, **(params or {})}, ttl=ttl)

    async def _genre_names(self, media_type: str) -> dict[int, str]:
        try:
            payload = await self._get(f"/genre/{media_type}/list", ttl=3600)
            return {row["id"]: row["name"] for row in payload.get("genres") or []
                    if isinstance(row, dict) and isinstance(row.get("id"), int) and row.get("name")}
        except ProviderError:
            return {}

    def map_media(self, payload: dict, media_type: str, genre_names: dict[int, str] | None = None,
                  *, full: bool = False) -> Media:
        name = payload.get("title") if media_type == "movie" else payload.get("name")
        release = payload.get("release_date") if media_type == "movie" else payload.get("first_air_date")
        genre_rows = payload.get("genres")
        genres = ([row["name"] for row in genre_rows if isinstance(row, dict) and row.get("name")]
                  if isinstance(genre_rows, list) else [])
        if not genres:
            genres = [(genre_names or {})[id_] for id_ in payload.get("genre_ids") or []
                      if id_ in (genre_names or {})]
        creators, cast = _credits(payload, media_type)
        runtime = payload.get("runtime") if media_type == "movie" else payload.get("number_of_episodes")
        seasons = [Season(number=row.get("season_number", 0), name=row.get("name") or "Season",
                          episode_count=row.get("episode_count"), air_date=row.get("air_date"),
                          poster_url=image_url(row.get("poster_path"), "w342"))
                   for row in payload.get("seasons") or [] if isinstance(row, dict)]
        next_episode = payload.get("next_episode_to_air") or {}
        return Media(
            id=f"tmdb:{media_type}:{payload['id']}", media_type=media_type, source="tmdb",
            source_id=payload["id"], title=name or payload.get("original_title") or payload.get("original_name") or "Untitled",
            year=_year(release), genres=genres, poster_url=image_url(payload.get("poster_path"), "w342"),
            backdrop_url=image_url(payload.get("backdrop_path"), "w1280"),
            summary_short=short_overview(payload.get("overview")),
            overview=payload.get("overview") or "",
            rating=round(float(payload["vote_average"]) * 10) if isinstance(payload.get("vote_average"), (int, float)) else None,
            runtime_or_episodes=runtime if isinstance(runtime, int) else None,
            status=payload.get("status"), director_or_creators=creators, cast=cast,
            trailer_key=_trailer(payload) if full else None,
            seasons=seasons, episodes=payload.get("number_of_episodes") if media_type == "tv" else None,
            networks=[row["name"] for row in payload.get("networks") or [] if isinstance(row, dict) and row.get("name")],
            next_episode_date=next_episode.get("air_date") if isinstance(next_episode, dict) else None,
            certification=_certification(payload, media_type) if full else None,
        )

    async def _cards(self, results: list[dict], media_type: str) -> tuple[list[Media], bool]:
        names = await self._genre_names(media_type)
        partial = False

        async def card(row: dict) -> Media | None:
            nonlocal partial
            if not isinstance(row, dict) or not isinstance(row.get("id"), int):
                return None
            try:
                detail = await self._get(f"/{media_type}/{row['id']}",
                                         {"append_to_response": "credits"}, ttl=3600)
                merged = {**row, **detail}
                return self.map_media(merged, media_type, names)
            except ProviderError:
                partial = True
                return self.map_media(row, media_type, names)

        cards = await asyncio.gather(*(card(row) for row in results))
        return [item for item in cards if item is not None], partial

    async def search(self, query: str, media_type: str) -> tuple[list[Media], bool]:
        payload = await self._get(f"/search/{media_type}", {"query": query, "include_adult": "false"}, ttl=600)
        return await self._cards((payload.get("results") or [])[:8], media_type)

    async def browse(self, media_type: str, category: str, genre: str | None, page: int) -> tuple[list[Media], bool, bool]:
        if genre:
            genre_id = GENRES.get(genre, {}).get(media_type)
            if genre_id is None:
                raise ValueError("Unknown genre.")
            sort_by = {"trending": "popularity.desc", "popular": "popularity.desc",
                       "top_rated": "vote_average.desc", "new": "primary_release_date.desc" if media_type == "movie" else "first_air_date.desc"}[category]
            params = {"page": page, "with_genres": genre_id, "sort_by": sort_by}
            if category == "top_rated":
                params["vote_count.gte"] = 50
            path = f"/discover/{media_type}"
        else:
            route = {"trending": f"/trending/{media_type}/week", "popular": f"/{media_type}/popular",
                     "top_rated": f"/{media_type}/top_rated",
                     "new": f"/{media_type}/now_playing" if media_type == "movie" else "/tv/on_the_air"}
            path, params = route[category], {"page": page}
        payload = await self._get(path, params, ttl=600)
        cards, partial = await self._cards((payload.get("results") or [])[:20], media_type)
        return cards, page < int(payload.get("total_pages") or 1), partial

    async def details(self, source_id: int, media_type: str) -> Media:
        append = "credits,videos,release_dates" if media_type == "movie" else "credits,videos,content_ratings"
        payload = await self._get(f"/{media_type}/{source_id}", {"append_to_response": append}, ttl=3600)
        payload.setdefault("id", source_id)
        return self.map_media(payload, media_type, await self._genre_names(media_type), full=True)

    async def similar(self, source_id: int, media_type: str) -> tuple[list[Media], bool]:
        try:
            payload = await self._get(f"/{media_type}/{source_id}/recommendations", ttl=600)
            rows = payload.get("results") or []
            if not rows:
                payload = await self._get(f"/{media_type}/{source_id}/similar", ttl=600)
                rows = payload.get("results") or []
        except ProviderError:
            payload = await self._get(f"/{media_type}/{source_id}/similar", ttl=600)
            rows = payload.get("results") or []
        return await self._cards(rows[:12], media_type)
