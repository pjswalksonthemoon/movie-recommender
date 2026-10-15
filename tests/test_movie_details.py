"""Movie detail and similar movie endpoint tests use offline mocked TMDB data."""
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import main
from app.recommender import MovieRecommender
from app.tmdb import TMDBError
from app.tmdb import TMDBClient


@pytest.fixture
def engine(tmp_path):
    pd.DataFrame([
        (1, "Alpha (2000)", "Drama"), (2, "Alpha Again (2001)", "Drama|Comedy"),
        (3, "Beta (2002)", "Action"), (4, "Rare (2003)", "Mystery"),
    ], columns=["movieId", "title", "genres"]).to_csv(tmp_path / "movies.csv", index=False)
    rows = [(user, movie, value) for user, values in enumerate([(5, 5, 1), (4, 4, 2), (1, 1, 5)], 1)
            for movie, value in zip([1, 2, 3], values)]
    rows += [(1, 4, 5)]
    pd.DataFrame(rows, columns=["userId", "movieId", "rating"]).to_csv(tmp_path / "ratings.csv", index=False)
    pd.DataFrame([(1, 101), (2, 102), (3, 103), (4, 104)], columns=["movieId", "tmdbId"]).to_csv(tmp_path / "links.csv", index=False)
    return MovieRecommender(tmp_path, min_movie_ratings=2, min_user_ratings=2)


@pytest.fixture
def client(engine, monkeypatch):
    class MockTMDB:
        enabled = True

        def __init__(self):
            self.payload = {}
            self.failure = False
            self.calls = []

        def get(self, path, **_kwargs):
            self.calls.append(path)
            if self.failure:
                raise TMDBError("TMDB is unavailable")
            return self.payload

        def close(self):
            pass

    tmdb = MockTMDB()
    monkeypatch.setattr(main, "get_engine", lambda: engine)
    monkeypatch.setattr(main, "TMDBClient", lambda _key: tmdb)
    with TestClient(main.app) as test_client:
        test_client.app.state.tmdb = tmdb
        yield test_client, tmdb


def test_movie_details_success(client):
    http, tmdb = client
    tmdb.payload = {
        "title": "Alpha on Film", "tagline": "A little tagline", "overview": "A story.",
        "release_date": "2000-04-01", "runtime": 98, "original_language": "en",
        "genres": [{"name": "Drama"}], "vote_average": 7.8, "vote_count": 123,
        "poster_path": "/poster.jpg", "backdrop_path": "/backdrop.jpg",
        "credits": {"crew": [{"job": "Director", "name": "A Director"},
                              {"job": "Writer", "name": "A Writer"}],
                    "cast": [{"name": f"Actor {i}", "character": "Hero", "profile_path": "/actor.jpg"} for i in range(15)]},
        "release_dates": {"results": [{"iso_3166_1": "US", "release_dates": [{"certification": "PG"}]}]},
        "videos": {"results": [{"site": "YouTube", "type": "Trailer", "key": "abc123XYZ"}]},
    }
    response = http.get("/api/movie/1")
    assert response.status_code == 200
    data = response.json()
    assert data["movie_id"] == 1 and data["title"] == "Alpha on Film"
    assert data["year"] == "2000" and data["runtime"] == 98
    assert data["poster"] == "https://image.tmdb.org/t/p/w500/poster.jpg"
    assert data["backdrop"] == "https://image.tmdb.org/t/p/w1280/backdrop.jpg"
    assert data["directors"] == ["A Director"] and data["writers"] == ["A Writer"]
    assert data["certification"] == "PG" and data["trailer_key"] == "abc123XYZ"
    assert len(data["cast"]) == 12 and data["limited"] is False
    assert tmdb.calls == ["/movie/101"]


def test_movie_details_missing_fields_and_missing_key(client, monkeypatch):
    http, tmdb = client
    tmdb.payload = {"credits": {}, "videos": {}}
    response = http.get("/api/movie/1")
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Alpha (2000)" and data["overview"] == ""
    assert data["genres"] == ["Drama"] and data["cast"] == [] and data["limited"] is False

    class NoKey:
        enabled = False
        def get(self, path):
            raise AssertionError("TMDB must not be called without a key")
        def close(self):
            pass

    monkeypatch.setattr(main, "TMDBClient", lambda _key: NoKey())
    with TestClient(main.app) as no_key_client:
        no_key = no_key_client.get("/api/movie/1").json()
    assert no_key["limited"] is True and no_key["title"] == "Alpha (2000)"
    assert no_key["genres"] == ["Drama"]


def test_tmdb_failure_is_graceful(client):
    http, tmdb = client
    tmdb.failure = True
    response = http.get("/api/movie/1")
    assert response.status_code == 200
    assert response.json()["limited"] is True
    assert "unavailable" in response.json()["notice"]
    similar = http.get("/api/movie/4/similar?n=4")
    assert similar.status_code == 200 and similar.json() == []


def test_similar_uses_collaborative_filtering_and_tmdb_fallback(client):
    http, tmdb = client
    result = http.get("/api/movie/1/similar?n=3").json()
    assert result[0]["movie_id"] == 2 and result[0]["score"] == pytest.approx(1)
    assert result[0]["genres"] == ["Drama", "Comedy"]
    assert all(item["movie_id"] != 1 for item in result)

    tmdb.payload = {"results": [{"id": 102, "title": "Alpha Again", "release_date": "2001-01-01",
                                  "poster_path": "/alpha.jpg", "genres": [{"name": "Drama"}]}]}
    fallback = http.get("/api/movie/4/similar?n=2").json()
    assert fallback == [{"id": 2, "movie_id": 2, "title": "Alpha Again", "year": "2001",
                         "genres": ["Drama"], "poster": "https://image.tmdb.org/t/p/w500/alpha.jpg", "score": None}]


def test_movie_endpoints_validate_unknown_ids_and_include_navigation_ids(client):
    http, _ = client
    assert http.get("/api/movie/0").status_code == 422
    assert http.get("/api/movie/999").status_code == 404
    assert http.get("/api/movie/1/similar?n=0").status_code == 422
    assert http.get("/api/search?q=alpha").json()[0] == {"movie_id": 1, "title": "Alpha (2000)"}
    assert "movie_id" in http.get("/api/movies/popular").json()[0]
    assert "movie_id" in http.get("/api/recommend?title=Alpha%20(2000)").json()[0]


def test_tmdb_response_cache_and_append_parameters(monkeypatch):
    client = TMDBClient("a-secret-key", ttl_seconds=60)
    calls = []

    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return {"title": "Cached title"}

    def mocked_get(url, params):
        calls.append((url, params))
        return Response()

    monkeypatch.setattr(client._client, "get", mocked_get)
    try:
        assert client.get("/movie/101", append_details=True) == client.get("/movie/101", append_details=True)
        assert len(calls) == 1
        assert calls[0][1]["append_to_response"] == "credits,videos,release_dates"
        assert calls[0][1]["api_key"] == "a-secret-key"
    finally:
        client.close()

