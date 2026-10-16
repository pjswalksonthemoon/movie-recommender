"""FastAPI routes and static frontend; run with ``uvicorn app.main:app --reload``."""
from contextlib import asynccontextmanager
import asyncio
from pathlib import Path
import os
import re
from typing import Annotated, Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .recommender import RecommendationError, get_engine
from .tmdb import TMDBClient, TMDBError, basic_card, image_url
from .auth import router as auth_router, validate_production_secret
from .media.anilist import AniListProvider
from .media.tmdb import TMDBProvider
from .media.service import MediaService
from .media.routes import router as media_router
from .watchlists import router as watchlist_router

load_dotenv()
STATIC = Path(__file__).parent / "static"
Title = Annotated[str, Query(min_length=1, max_length=300, pattern=r"\S")]
Count = Annotated[int, Query(ge=1, le=50)]
TMDB_IMAGE = "https://image.tmdb.org/t/p/"


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_production_secret()
    app.state.engine = get_engine()
    app.state.tmdb = TMDBClient(os.getenv("TMDB_API_KEY"))
    app.state.media = MediaService(TMDBProvider(os.getenv("TMDB_API_KEY")),
                                   AniListProvider(), app.state.engine)
    try:
        yield
    finally:
        app.state.tmdb.close()
        await app.state.tmdb.aclose()
        await app.state.media.close()


app = FastAPI(title="Wachl", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")
app.include_router(auth_router)
app.include_router(media_router)
app.include_router(watchlist_router)


def _catalog_card(movie_id: int) -> dict[str, Any]:
    row = app.state.engine.catalog.loc[movie_id]
    return basic_card(movie_id, str(row.title), str(row.genres))


async def _enrich_cards(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Enrich one list concurrently; each failed card retains its MovieLens data."""
    engine = app.state.engine
    async def one(row: dict[str, Any]) -> dict[str, Any]:
        movie_id = int(row["movie_id"])
        basic = _catalog_card(movie_id)
        tmdb_id = engine.tmdb_ids.get(movie_id)
        summary = await app.state.tmdb.card_summary(tmdb_id, basic)
        extras = {key: value for key, value in row.items() if key not in {"title", "genres", "year", "poster", "poster_url"}}
        return {**summary, **extras, "media_id": f"tmdb:movie:{tmdb_id}" if tmdb_id else None}
    return await asyncio.gather(*(one(row) for row in rows))


@app.get("/api/movielens/search")
async def search(q: Title):
    return await _enrich_cards(app.state.engine.search(q))


@app.get("/api/recommend")
async def recommend(title: Title, n: Count = 10):
    try:
        return await _enrich_cards(app.state.engine.get_recommendations(title, n))
    except RecommendationError as exc:
        raise HTTPException(status_code=404 if exc.code == "unknown_title" else 422,
                            detail={"code": exc.code, "message": str(exc), "matches": exc.matches}) from exc


@app.get("/api/movies/popular")
async def popular():
    return await _enrich_cards(app.state.engine.popular())


def _year(title: str, release_date: str | None = None) -> str | None:
    date_year = (release_date or "")[:4]
    if date_year.isdigit():
        return date_year
    match = re.search(r"\((\d{4})\)\s*$", title)
    return match.group(1) if match else None


def _basic_movie(movie_id: int) -> dict[str, Any]:
    engine = app.state.engine
    rows = engine.movies[engine.movies.movieId == movie_id]
    if rows.empty:
        raise HTTPException(status_code=404, detail="Movie not found.")
    row = rows.iloc[0]
    title = str(row.title)
    return {
        "movie_id": movie_id, "media_id": f"tmdb:movie:{engine.tmdb_ids[movie_id]}" if movie_id in engine.tmdb_ids else None,
        "title": title, "year": _year(title), "tagline": "",
        "overview": "", "release_date": None, "runtime": None, "original_language": None,
        "genres": [genre for genre in str(row.genres).split("|") if genre and genre != "(no genres listed)"],
        "vote_average": None, "vote_count": 0, "poster": None, "backdrop": None,
        "directors": [], "writers": [], "certification": None, "cast": [],
        "trailer_key": None, "limited": True,
    }


def _certification(payload: dict[str, Any]) -> str | None:
    release_data = payload.get("release_dates") or {}
    if not isinstance(release_data, dict):
        return None
    countries = release_data.get("results") or []
    countries = [country for country in countries if isinstance(country, dict)]
    ordered = sorted(countries, key=lambda item: item.get("iso_3166_1") != "US")
    for country in ordered:
        for release in (country.get("release_dates") or []):
            if not isinstance(release, dict):
                continue
            certification = release.get("certification")
            if certification:
                return certification
    return None


def _tmdb_movie(payload: dict[str, Any], basic: dict[str, Any]) -> dict[str, Any]:
    credits = payload.get("credits") or {}
    if not isinstance(credits, dict):
        credits = {}
    crew = credits.get("crew") or []
    cast = credits.get("cast") or []
    if not isinstance(crew, list):
        crew = []
    if not isinstance(cast, list):
        cast = []
    video_data = payload.get("videos") or {}
    videos = (video_data.get("results") or []) if isinstance(video_data, dict) else []
    trailer = next((item for item in videos if isinstance(item, dict) and item.get("site") == "YouTube" and item.get("type") == "Trailer"), None)
    release_date = payload.get("release_date") or None
    return {
        **basic,
        "title": payload.get("title") or basic["title"], "tagline": payload.get("tagline") or "",
        "overview": payload.get("overview") or "", "release_date": release_date,
        "year": _year(basic["title"], release_date), "runtime": payload.get("runtime"),
        "original_language": payload.get("original_language"),
        "genres": [genre["name"] for genre in (payload.get("genres") or []) if isinstance(genre, dict) and genre.get("name")] or basic["genres"],
        "vote_average": payload.get("vote_average"), "vote_count": payload.get("vote_count") or 0,
        "poster": f"{TMDB_IMAGE}w500{payload['poster_path']}" if payload.get("poster_path") else None,
        "backdrop": f"{TMDB_IMAGE}w1280{payload['backdrop_path']}" if payload.get("backdrop_path") else None,
        "directors": [{"id": person.get("id"), "name": person["name"]} for person in crew if isinstance(person, dict) and person.get("job") == "Director" and person.get("name")],
        "writers": [{"id": person.get("id"), "name": person["name"]} for person in crew if isinstance(person, dict) and person.get("job") in {"Writer", "Screenplay", "Story"} and person.get("name")],
        "certification": _certification(payload),
        "cast": [{"id": person.get("id"), "name": person.get("name", "Unknown"), "character": person.get("character") or "",
                  "profile": f"{TMDB_IMAGE}w185{person['profile_path']}" if person.get("profile_path") else None}
                 for person in cast[:12] if isinstance(person, dict)],
        "trailer_key": trailer.get("key") if trailer else None, "limited": False,
    }


@app.get("/api/movie/{movie_id}")
def movie_details(movie_id: int):
    if movie_id < 1:
        raise HTTPException(status_code=422, detail="movie_id must be positive.")
    basic = _basic_movie(movie_id)
    tmdb_id = app.state.engine.tmdb_ids.get(movie_id)
    if not app.state.tmdb.enabled or not tmdb_id:
        return basic
    try:
        return _tmdb_movie(app.state.tmdb.get(f"/movie/{tmdb_id}", append_details=True), basic)
    except TMDBError:
        return {**basic, "notice": "Movie details are temporarily unavailable from TMDB."}


def _movie_result(movie_id: int, title: str, genres: str | list[str], score: float | None,
                  poster: str | None = None, release_date: str | None = None) -> dict[str, Any]:
    genre_list = genres if isinstance(genres, list) else [part for part in genres.split("|") if part and part != "(no genres listed)"]
    return {"id": movie_id, "movie_id": movie_id, "title": title, "year": _year(title, release_date),
            "genres": genre_list, "poster": poster, "score": score}


@app.get("/api/movie/{movie_id}/similar")
async def similar_movies(movie_id: int, n: Count = 12):
    basic = _basic_movie(movie_id)
    engine = app.state.engine
    results: list[dict[str, Any]] = []
    try:
        neighbors = engine.get_recommendations(basic["title"], n)
        for neighbor in neighbors:
            other_id = neighbor["movie_id"]
            results.append(_movie_result(other_id, neighbor["title"], neighbor["genres"], neighbor["score"]))
        if results:
            return await _enrich_cards(results)
    except RecommendationError:
        pass

    tmdb_id = engine.tmdb_ids.get(movie_id)
    if not app.state.tmdb.enabled or not tmdb_id:
        return await _enrich_cards(results)
    try:
        payload = app.state.tmdb.get(f"/movie/{tmdb_id}/similar")
    except TMDBError:
        return await _enrich_cards(results)
    id_by_tmdb = {tmdb: movie for movie, tmdb in engine.tmdb_ids.items()}
    similar_results = payload.get("results") or []
    if not isinstance(similar_results, list):
        return await _enrich_cards(results)
    genre_map: dict[int, str] = {}
    if any(isinstance(item, dict) and item.get("genre_ids") for item in similar_results):
        try:
            genre_payload = app.state.tmdb.get("/genre/movie/list")
            genre_map = {genre["id"]: genre["name"] for genre in (genre_payload.get("genres") or [])
                         if isinstance(genre, dict) and isinstance(genre.get("id"), int) and genre.get("name")}
        except TMDBError:
            pass
    for item in similar_results:
        if not isinstance(item, dict):
            continue
        mapped_id = id_by_tmdb.get(item.get("id"))
        if not mapped_id or mapped_id == movie_id:
            continue
        genres = [genre["name"] for genre in (item.get("genres") or []) if isinstance(genre, dict) and genre.get("name")]
        if not genres:
            genres = [genre_map[genre_id] for genre_id in item.get("genre_ids", []) if genre_id in genre_map]
        results.append(_movie_result(mapped_id, item.get("title") or "Untitled movie", genres or basic["genres"], None,
                                     f"{TMDB_IMAGE}w500{item['poster_path']}" if item.get("poster_path") else None,
                                     item.get("release_date")))
        if len(results) == n:
            break
    return await _enrich_cards(results)


@app.get("/api/person/{person_id}")
def person_details(person_id: int):
    """Return a TMDB biography plus up to 24 popular film credits."""
    if person_id < 1:
        raise HTTPException(status_code=422, detail="person_id must be positive.")
    tmdb = app.state.tmdb
    if not tmdb.enabled:
        raise HTTPException(status_code=503, detail="Person details require TMDB_API_KEY.")
    try:
        payload = tmdb.get(f"/person/{person_id}", append_to_response="movie_credits")
    except TMDBError as exc:
        raise HTTPException(status_code=404 if exc.status_code == 404 else 502,
                            detail="Person not found." if exc.status_code == 404 else "TMDB is unavailable right now.") from exc
    credits = payload.get("movie_credits") or {}
    if not isinstance(credits, dict):
        credits = {}
    cast = credits.get("cast") or []
    crew = credits.get("crew") or []
    credits_by_movie: dict[int, dict[str, Any]] = {}
    for item in cast if isinstance(cast, list) else []:
        if isinstance(item, dict) and isinstance(item.get("id"), int):
            credits_by_movie[item["id"]] = {**item, "role": f"as {item['character']}" if item.get("character") else "Actor"}
    for item in crew if isinstance(crew, list) else []:
        if isinstance(item, dict) and isinstance(item.get("id"), int) and item.get("job") == "Director":
            credits_by_movie.setdefault(item["id"], {**item, "role": "Director"})
    movie_ids = {tmdb_id: movie_id for movie_id, tmdb_id in app.state.engine.tmdb_ids.items()}
    filmography = []
    for item in sorted(credits_by_movie.values(), key=lambda credit: float(credit.get("popularity") or 0), reverse=True)[:24]:
        release = item.get("release_date") or ""
        filmography.append({
            "movie_id": movie_ids.get(item["id"]), "tmdb_id": item["id"],
            "title": item.get("title") or item.get("original_title") or "Untitled movie",
            "year": release[:4] if isinstance(release, str) and release[:4].isdigit() else None,
            "poster_url": image_url(item.get("poster_path"), "w342"),
            "role": item["role"],
        })
    return {
        "id": person_id, "name": payload.get("name") or "Unknown person",
        "photo_url": image_url(payload.get("profile_path"), "w500"),
        "biography": payload.get("biography") or "",
        "known_for_department": payload.get("known_for_department") or "",
        "birthday": payload.get("birthday") or None,
        "place_of_birth": payload.get("place_of_birth") or None,
        "filmography": filmography,
    }


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")
