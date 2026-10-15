"""Deterministic engine tests with a small, offline synthetic ratings dataset."""
import pandas as pd
import pytest

from app.recommender import MovieRecommender, RecommendationError


@pytest.fixture
def engine(tmp_path):
    pd.DataFrame([
        (1, "Alpha (2000)", "Drama"), (2, "Alpha Again (2001)", "Drama|Comedy"),
        (3, "Beta (2002)", "Action"), (4, "Rare (2003)", "Mystery"),
        (5, "Gamma (2004)", "Comedy"),
    ], columns=["movieId", "title", "genres"]).to_csv(tmp_path / "movies.csv", index=False)
    rows = [(u, m, value) for u, values in enumerate([(5, 5, 1, 2), (4, 4, 2, 3), (1, 1, 5, 4)], 1)
            for m, value in zip([1, 2, 3, 5], values)]
    rows.extend([(1, 4, 5), (99, 4, 3)])
    pd.DataFrame(rows, columns=["userId", "movieId", "rating"]).to_csv(tmp_path / "ratings.csv", index=False)
    return MovieRecommender(tmp_path, min_movie_ratings=2, min_user_ratings=2)


def test_most_similar_and_self_exclusion(engine):
    result = engine.get_recommendations("Alpha (2000)", 3)
    assert result[0]["title"] == "Alpha Again (2001)"
    assert result[0]["score"] == pytest.approx(1)
    assert len(result) == 3
    assert all(item["title"] != "Alpha (2000)" for item in result)
    assert all(0 <= item["score"] <= 1 for item in result)
    assert [x["score"] for x in result] == sorted([x["score"] for x in result], reverse=True)


def test_case_whitespace_and_limit(engine):
    assert engine.get_recommendations("  ALPHA (2000)  ", 1) == engine.get_recommendations("Alpha (2000)", 1)
    assert len(engine.get_recommendations("Beta", 50)) == 3


@pytest.mark.parametrize("title,code", [("Alpha", "ambiguous_title"), ("Alhpa (2000)", "unknown_title"), ("Rare (2003)", "insufficient_ratings")])
def test_lookup_errors(engine, title, code):
    with pytest.raises(RecommendationError) as exc:
        engine.get_recommendations(title)
    assert exc.value.code == code
    if code != "insufficient_ratings":
        assert "Alpha (2000)" in exc.value.matches


@pytest.mark.parametrize("title,n", [("", 10), ("   ", 10), (None, 10), ("Alpha", 0), ("Alpha", 51), ("Alpha", True), ("Alpha", 1.2)])
def test_invalid_inputs(engine, title, n):
    with pytest.raises(ValueError):
        engine.get_recommendations(title, n)


def test_search_is_literal_and_popular_is_counted(engine):
    assert engine.search("[") == []
    assert len(engine.search("alpha")) == 2
    assert engine.search("alpha")[0]["movie_id"] == 1
    assert engine.popular()[0]["rating_count"] == 3
    assert "movie_id" in engine.popular()[0]


def test_model_reused(engine):
    model = engine.model
    engine.get_recommendations("Beta")
    assert engine.model is model


def test_static_export_matches_engine(engine, tmp_path):
    import json
    from app.build_static import export_site
    destination = tmp_path / "site"
    export_site(engine, destination)
    catalog = json.loads((destination / "movies.json").read_text(encoding="utf-8"))
    neighbors = json.loads((destination / "recommendations.json").read_text())
    by_id = {movie["movieId"]: movie for movie in catalog}
    actual = [{"movie_id": movie_id, "title": by_id[movie_id]["title"], "genres": by_id[movie_id]["genres"], "score": score}
              for movie_id, score in neighbors["1"]]
    assert actual == engine.get_recommendations("Alpha (2000)", 50)
    assert "4" not in neighbors


def test_api(engine, monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    monkeypatch.setattr(main, "get_engine", lambda: engine)
    with TestClient(main.app) as client:
        assert client.get("/").status_code == 200
        assert client.get("/static/script.js").status_code == 200
        assert len(client.get("/api/search", params={"q": "alpha"}).json()) == 2
        assert client.get("/api/movies/popular").status_code == 200
        response = client.get("/api/recommend", params={"title": "Alpha (2000)", "n": 1})
        assert response.status_code == 200
        assert response.json()[0]["title"] == "Alpha Again (2001)"
        for params in ({"title": "   "}, {"title": "Alpha", "n": 0}, {"title": "Alpha", "n": 51}):
            assert client.get("/api/recommend", params=params).status_code == 422
        assert client.get("/api/search", params={"q": " "}).status_code == 422
        assert client.get("/api/recommend", params={"title": "Alhpa (2000)"}).status_code == 404
        assert client.get("/api/recommend", params={"title": "Rare (2003)"}).json()["detail"]["code"] == "insufficient_ratings"

