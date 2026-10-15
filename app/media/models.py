"""One public representation for films, television and anime."""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field


class Credit(BaseModel):
    id: int | None = None
    name: str
    character: str | None = None
    photo_url: str | None = None
    external_url: str | None = None


class Season(BaseModel):
    number: int
    name: str
    episode_count: int | None = None
    air_date: str | None = None
    poster_url: str | None = None


class Relation(BaseModel):
    id: str
    title: str
    relation: str
    poster_url: str | None = None


class Media(BaseModel):
    id: str
    media_type: Literal["movie", "tv", "anime"]
    source: Literal["tmdb", "anilist"]
    source_id: int
    title: str
    year: str | None = None
    genres: list[str] = Field(default_factory=list)
    poster_url: str | None = None
    backdrop_url: str | None = None
    summary_short: str = ""
    overview: str = ""
    rating: int | None = None
    runtime_or_episodes: int | None = None
    status: str | None = None
    director_or_creators: list[Credit] = Field(default_factory=list)
    cast: list[Credit] = Field(default_factory=list)
    trailer_key: str | None = None
    seasons: list[Season] = Field(default_factory=list)
    episodes: int | None = None
    english_title: str | None = None
    format: str | None = None
    studio: str | None = None
    tags: list[str] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)
    networks: list[str] = Field(default_factory=list)
    next_episode_date: str | None = None
    role: str | None = None
    match_score: float | None = None
    movielens_id: int | None = None
    certification: str | None = None


MEDIA_ID = re.compile(r"^(?:tmdb:(?:movie|tv):[1-9]\d*|anilist:[1-9]\d*)$")


def parse_media_id(value: str) -> tuple[str, str, int]:
    """Parse a stable public id without allowing arbitrary provider paths."""
    if not MEDIA_ID.fullmatch(value):
        raise ValueError("Invalid media id.")
    parts = value.split(":")
    return ("anilist", "anime", int(parts[1])) if len(parts) == 2 else ("tmdb", parts[1], int(parts[2]))
