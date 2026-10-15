"""FastAPI routes and static frontend; start with uvicorn app.main:app --reload."""
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .recommender import RecommendationError, get_engine

STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.engine = get_engine()
    yield


app = FastAPI(title="Reelwise", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")
Title = Annotated[str, Query(min_length=1, max_length=300, pattern=r"\S")]


@app.get("/api/search")
def search(q: Title):
    return app.state.engine.search(q)


@app.get("/api/recommend")
def recommend(title: Title, n: Annotated[int, Query(ge=1, le=50)] = 10):
    try:
        return app.state.engine.get_recommendations(title, n)
    except RecommendationError as exc:
        raise HTTPException(status_code=404 if exc.code == "unknown_title" else 422,
                            detail={"code": exc.code, "message": str(exc), "matches": exc.matches}) from exc


@app.get("/api/movies/popular")
def popular():
    return app.state.engine.popular()


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")
