"""Provider orchestration, partial results, and MovieLens blending."""
from __future__ import annotations

import asyncio
from typing import Any

from .cache import ProviderError
from .models import Media, parse_media_id
from .tmdb import TMDBProvider
from .anilist import AniListProvider
from ..recommender import MovieRecommender, RecommendationError


class MediaService:
    def __init__(self, tmdb: TMDBProvider, anilist: AniListProvider, engine: MovieRecommender):
        self.tmdb = tmdb
        self.anilist = anilist
        self.engine = engine
        self.movie_id_by_tmdb = {tmdb_id: movie_id for movie_id, tmdb_id in engine.tmdb_ids.items()}

    async def close(self):
        await asyncio.gather(self.tmdb.close(), self.anilist.close())

    def _with_movielens(self, media: Media) -> Media:
        if media.media_type == "movie" and media.source == "tmdb":
            media.movielens_id = self.movie_id_by_tmdb.get(media.source_id)
        return media

    async def search(self, query: str, media_type: str) -> dict[str, Any]:
        jobs = []
        if media_type in {"all", "movie"}:
            jobs.append(self.tmdb.search(query, "movie"))
        if media_type in {"all", "tv"}:
            jobs.append(self.tmdb.search(query, "tv"))
        if media_type in {"all", "anime"}:
            jobs.append(self.anilist.search(query))
        responses = await asyncio.gather(*jobs, return_exceptions=True)
        items: list[Media] = []
        partial = False
        for response in responses:
            if isinstance(response, Exception):
                partial = True
                continue
            if isinstance(response, tuple):
                cards, incomplete = response
                partial |= incomplete
            else:
                cards = response
            items.extend(self._with_movielens(item) for item in cards)
        return {"items": items, "partial": partial}

    async def browse(self, media_type: str, category: str, genre: str | None, page: int) -> dict[str, Any]:
        try:
            if media_type == "anime":
                items, more = await self.anilist.browse(category, genre, page)
                incomplete = False
            else:
                items, more, incomplete = await self.tmdb.browse(media_type, category, genre, page)
            return {"items": [self._with_movielens(item) for item in items],
                    "page": page, "has_more": more, "partial": incomplete}
        except ProviderError:
            return {"items": [], "page": page, "has_more": False, "partial": True}

    async def details(self, media_id: str) -> Media:
        source, media_type, source_id = parse_media_id(media_id)
        if source == "anilist":
            return await self.anilist.details(source_id)
        return self._with_movielens(await self.tmdb.details(source_id, media_type))

    async def similar(self, media_id: str) -> dict[str, Any]:
        source, media_type, source_id = parse_media_id(media_id)
        if source == "anilist":
            try:
                return {"items": await self.anilist.similar(source_id), "partial": False}
            except ProviderError:
                return {"items": [], "partial": True}
        items: list[Media] = []
        partial = False
        if media_type == "movie":
            movie_id = self.movie_id_by_tmdb.get(source_id)
            if movie_id:
                title = self.engine.catalog.loc[movie_id].title
                try:
                    neighbors = self.engine.get_recommendations(title, 5)
                    async def neighbor_card(row: dict) -> Media | None:
                        tmdb_id = self.engine.tmdb_ids.get(row["movie_id"])
                        if not tmdb_id:
                            return None
                        try:
                            card = await self.tmdb.details(tmdb_id, "movie")
                            card.match_score = row["score"]
                            return self._with_movielens(card)
                        except ProviderError:
                            return None
                    enriched = await asyncio.gather(*(neighbor_card(row) for row in neighbors))
                    items.extend(item for item in enriched if item is not None)
                    partial |= len(items) < len(neighbors)
                except RecommendationError:
                    pass
        try:
            provider_items, incomplete = await self.tmdb.similar(source_id, media_type)
            partial |= incomplete
            seen = {item.id for item in items}
            items.extend(self._with_movielens(item) for item in provider_items if item.id not in seen)
        except ProviderError:
            partial = True
        return {"items": items[:12], "partial": partial}
