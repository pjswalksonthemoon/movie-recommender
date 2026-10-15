"""Authenticated personal lists with ownership checks and cached media fields."""
from __future__ import annotations

import asyncio
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import current_user, require_csrf
from .db import User, Watchlist, WatchlistItem, get_db
from .media.cache import ProviderError
from .media.models import Media, parse_media_id

router = APIRouter(prefix="/api/watchlists", tags=["watchlists"])
Db = Annotated[Session, Depends(get_db)]
Owner = Annotated[User, Depends(current_user)]
Csrf = Annotated[None, Depends(require_csrf)]
Status = Literal["Plan to watch", "Watching", "Watched"]


class ListBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Choose a list name.")
        return value


class AddItem(BaseModel):
    media_id: str
    status: Status = "Plan to watch"
    rating: int | None = Field(default=None, ge=1, le=10)


class UpdateItem(BaseModel):
    status: Status | None = None
    rating: int | None = Field(default=None, ge=1, le=10)


def _owned(db: Session, user_id: int, list_id: int) -> Watchlist:
    watchlist = db.scalar(select(Watchlist).where(Watchlist.id == list_id, Watchlist.user_id == user_id))
    if not watchlist:
        raise HTTPException(status_code=404, detail="List not found.")
    return watchlist


def _item(db: Session, watchlist_id: int, media_id: str) -> WatchlistItem:
    result = db.scalar(select(WatchlistItem).where(WatchlistItem.watchlist_id == watchlist_id,
                                                   WatchlistItem.media_id == media_id))
    if not result:
        raise HTTPException(status_code=404, detail="Item not found.")
    return result


def _list_record(watchlist: Watchlist, count: int) -> dict:
    return {"id": watchlist.id, "name": watchlist.name, "item_count": count,
            "created_at": watchlist.created_at.isoformat()}


def _item_record(item: WatchlistItem, media: Media | None = None) -> dict:
    source, media_type, source_id = parse_media_id(item.media_id)
    fallback = Media(id=item.media_id, media_type=media_type, source=source, source_id=source_id,
                     title=item.title, poster_url=item.poster_url)
    return {"media_id": item.media_id, "media_type": item.media_type, "status": item.status,
            "rating": item.rating, "added_at": item.created_at.isoformat(),
            "media": (media or fallback).model_dump()}


@router.get("")
def get_lists(db: Db, user: Owner):
    rows = db.execute(select(Watchlist, func.count(WatchlistItem.id))
                      .outerjoin(WatchlistItem, Watchlist.id == WatchlistItem.watchlist_id)
                      .where(Watchlist.user_id == user.id)
                      .group_by(Watchlist.id).order_by(Watchlist.created_at, Watchlist.id)).all()
    return [_list_record(watchlist, count) for watchlist, count in rows]


@router.post("", status_code=201)
def create_list(body: ListBody, db: Db, user: Owner, _csrf: Csrf):
    watchlist = Watchlist(user_id=user.id, name=body.name)
    db.add(watchlist)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="You already have a list with that name.") from exc
    return _list_record(watchlist, 0)


@router.patch("/{list_id}")
def rename_list(list_id: int, body: ListBody, db: Db, user: Owner, _csrf: Csrf):
    watchlist = _owned(db, user.id, list_id)
    watchlist.name = body.name
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="You already have a list with that name.") from exc
    return _list_record(watchlist, len(watchlist.items))


@router.delete("/{list_id}")
def delete_list(list_id: int, db: Db, user: Owner, _csrf: Csrf):
    db.delete(_owned(db, user.id, list_id))
    db.commit()
    return {"ok": True}


@router.get("/{list_id}")
async def get_list(list_id: int, request: Request, db: Db, user: Owner):
    watchlist = _owned(db, user.id, list_id)
    items = list(db.scalars(select(WatchlistItem).where(WatchlistItem.watchlist_id == list_id)
                            .order_by(WatchlistItem.created_at.desc(), WatchlistItem.id.desc())))

    async def hydrate(item: WatchlistItem):
        try:
            return await request.app.state.media.details(item.media_id)
        except (ProviderError, ValueError):
            return None

    media = await asyncio.gather(*(hydrate(item) for item in items))
    return {**_list_record(watchlist, len(items)),
            "items": [_item_record(item, current) for item, current in zip(items, media)]}


@router.post("/{list_id}/items", status_code=201)
async def add_item(list_id: int, body: AddItem, request: Request, db: Db, user: Owner, _csrf: Csrf):
    watchlist = _owned(db, user.id, list_id)
    try:
        parse_media_id(body.media_id)
        media = await request.app.state.media.details(body.media_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail="Could not load this title right now.") from exc
    item = WatchlistItem(watchlist_id=watchlist.id, media_id=media.id, media_type=media.media_type,
                         title=media.title[:500], poster_url=media.poster_url, status=body.status, rating=body.rating)
    db.add(item)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="This title is already in that list.") from exc
    return _item_record(item, media)


@router.patch("/{list_id}/items/{media_id}")
def update_item(list_id: int, media_id: str, body: UpdateItem, db: Db, user: Owner, _csrf: Csrf):
    watchlist = _owned(db, user.id, list_id)
    item = _item(db, watchlist.id, media_id)
    if "status" in body.model_fields_set:
        if body.status is None:
            raise HTTPException(status_code=422, detail="Choose a status.")
        item.status = body.status
    if "rating" in body.model_fields_set:
        item.rating = body.rating
    db.commit()
    return _item_record(item)


@router.delete("/{list_id}/items/{media_id}")
def remove_item(list_id: int, media_id: str, db: Db, user: Owner, _csrf: Csrf):
    watchlist = _owned(db, user.id, list_id)
    db.delete(_item(db, watchlist.id, media_id))
    db.commit()
    return {"ok": True}
