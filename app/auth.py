"""Cookie-based authentication, CSRF checks, and per-IP auth throttling."""
from __future__ import annotations

from collections import defaultdict, deque
from datetime import timedelta
import hashlib
import hmac
import os
import re
import secrets
import time
from typing import Annotated

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .db import LoginSession, User, Watchlist, get_db, utcnow

router = APIRouter(prefix="/api/auth", tags=["accounts"])
Db = Annotated[Session, Depends(get_db)]
hasher = PasswordHasher()
_attempts: dict[tuple[str, str], deque[float]] = defaultdict(deque)
COOKIE_NAME = "reelwise_session"
SESSION_AGE = 30 * 24 * 60 * 60


class RegisterBody(BaseModel):
    email: str = Field(max_length=320)
    username: str = Field(min_length=3, max_length=24, pattern=r"^[A-Za-z0-9_]+$")
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        value = value.strip().casefold()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Enter a valid email address.")
        return value


class LoginBody(BaseModel):
    email: str
    password: str


def _secret() -> str:
    return os.getenv("SECRET_KEY") or "development-only-change-me"


def validate_production_secret() -> None:
    if os.getenv("APP_ENV", "development").casefold() == "production" and _secret() in {
        "development-only-change-me", "change-this-for-production",
    }:
        raise RuntimeError("Set a unique SECRET_KEY before starting in production mode.")


def _token_hash(token: str) -> str:
    return hmac.new(_secret().encode(), token.encode(), hashlib.sha256).hexdigest()


def _limit(request: Request, action: str) -> None:
    address = request.client.host if request.client else "unknown"
    key = (address, action)
    attempts = _attempts[key]
    now = time.monotonic()
    while attempts and now - attempts[0] > 60:
        attempts.popleft()
    if len(attempts) >= 5:
        raise HTTPException(status_code=429, detail="Too many attempts. Try again in a minute.")
    attempts.append(now)


def require_action_header(request: Request) -> None:
    """Custom header blocks cross-site form posts; Origin is checked when supplied."""
    if request.headers.get("x-reelwise-request") != "1":
        raise HTTPException(status_code=403, detail="Request confirmation header is missing.")
    origin = request.headers.get("origin")
    # Railway terminates HTTPS before forwarding to Uvicorn. Compare the public
    # origin with the forwarded scheme and Host instead of the internal URL.
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme).split(",", 1)[0].strip()
    host = request.headers.get("host", "")
    expected_origin = f"{scheme}://{host}"
    if origin and origin.rstrip("/") != expected_origin:
        raise HTTPException(status_code=403, detail="Cross-origin request rejected.")


def current_session(request: Request, db: Db) -> LoginSession:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Log in to continue.")
    session = db.get(LoginSession, _token_hash(token))
    if not session or session.expires_at.replace(tzinfo=None) <= utcnow().replace(tzinfo=None):
        raise HTTPException(status_code=401, detail="Log in to continue.")
    return session


def current_user(session: Annotated[LoginSession, Depends(current_session)], db: Db) -> User:
    user = db.get(User, session.user_id)
    if not user:
        raise HTTPException(status_code=401, detail="Log in to continue.")
    return user


def require_csrf(request: Request, session: Annotated[LoginSession, Depends(current_session)]) -> None:
    require_action_header(request)
    token = request.headers.get("x-csrf-token", "")
    if not hmac.compare_digest(token, session.csrf_token):
        raise HTTPException(status_code=403, detail="Session confirmation failed. Refresh and try again.")


def _public(user: User, csrf_token: str) -> dict:
    return {"id": user.id, "email": user.email, "username": user.username, "csrf_token": csrf_token}


def _issue(user: User, db: Session, response: Response, request: Request) -> dict:
    token = secrets.token_urlsafe(48)
    csrf_token = secrets.token_urlsafe(32)
    db.add(LoginSession(token_hash=_token_hash(token), user_id=user.id, csrf_token=csrf_token,
                        expires_at=utcnow() + timedelta(seconds=SESSION_AGE)))
    db.commit()
    public_scheme = request.headers.get("x-forwarded-proto", request.url.scheme).split(",", 1)[0].strip()
    response.set_cookie(COOKIE_NAME, token, max_age=SESSION_AGE, httponly=True,
                        secure=public_scheme == "https", samesite="lax", path="/")
    return _public(user, csrf_token)


@router.post("/register", status_code=201)
def register(body: RegisterBody, request: Request, response: Response, db: Db):
    require_action_header(request)
    _limit(request, "register")
    username = body.username.casefold()
    if db.scalar(select(User.id).where((User.email == body.email) | (User.username == username))):
        raise HTTPException(status_code=409, detail="Email or username already in use.")
    user = User(email=body.email, username=username, password_hash=hasher.hash(body.password))
    db.add(user)
    try:
        db.flush()
        db.add(Watchlist(user_id=user.id, name="Watchlist"))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Email or username already in use.") from exc
    return _issue(user, db, response, request)


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response, db: Db):
    require_action_header(request)
    _limit(request, "login")
    user = db.scalar(select(User).where(User.email == body.email.strip().casefold()))
    try:
        valid = bool(user and hasher.verify(user.password_hash, body.password))
    except (VerifyMismatchError, VerificationError):
        valid = False
    if not valid:
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    return _issue(user, db, response, request)


@router.post("/logout")
def logout(request: Request, response: Response, db: Db,
           session: Annotated[LoginSession, Depends(current_session)],
           _csrf: Annotated[None, Depends(require_csrf)]):
    db.delete(session)
    db.commit()
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
def me(session: Annotated[LoginSession, Depends(current_session)],
       user: Annotated[User, Depends(current_user)]):
    return _public(user, session.csrf_token)
