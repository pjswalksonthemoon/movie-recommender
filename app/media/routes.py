"""Unified live catalogue endpoints; provider details stay in MediaService."""
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request

from .cache import ProviderError
from .models import parse_media_id

router = APIRouter(tags=["media"])
SearchType = Literal["all", "movie", "tv", "anime"]
BrowseType = Literal["movie", "tv", "anime"]
Category = Literal["trending", "popular", "top_rated", "new"]
QueryText = Annotated[str, Query(min_length=1, max_length=200, pattern=r"\S")]


@router.get("/api/search")
async def search(q: QueryText, request: Request, type: SearchType = "all"):
    return await request.app.state.media.search(q.strip(), type)


@router.get("/api/browse")
async def browse(request: Request, type: BrowseType, category: Category,
                 genre: Annotated[str | None, Query(max_length=60)] = None,
                 page: Annotated[int, Query(ge=1, le=500)] = 1):
    try:
        return await request.app.state.media.browse(type, category, genre or None, page)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/api/media/{media_id}/similar")
async def similar(media_id: str, request: Request):
    try:
        parse_media_id(media_id)
        return await request.app.state.media.similar(media_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/api/media/{media_id}")
async def details(media_id: str, request: Request):
    try:
        parse_media_id(media_id)
        return await request.app.state.media.details(media_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(status_code=404 if exc.status_code == 404 else 502,
                            detail="Media not found." if exc.status_code == 404 else "Media provider is unavailable.") from exc
