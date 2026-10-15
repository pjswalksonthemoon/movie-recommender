# Reelwise · movie recommendations

A runnable FastAPI app with an in-memory, item-based collaborative filtering engine and a responsive HTML/CSS/JavaScript frontend. No database, frontend build, account, or API key is needed.

## Setup and run

Install Python 3.11 or newer (tested on Python 3.13). Open a terminal in this `movie-recommender` directory.

```sh
python -m venv .venv
```

Activate it on Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Or on macOS/Linux:

```sh
source .venv/bin/activate
```

Install and start:

```sh
python -m pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000. API documentation is at http://127.0.0.1:8000/docs. Stop with Ctrl+C. If activation is restricted on Windows, run `.venv\Scripts\python.exe -m pip install -r requirements.txt` and `.venv\Scripts\python.exe -m uvicorn app.main:app --reload` instead.

On first startup, the app downloads the official MovieLens `ml-latest-small` archive and puts `movies.csv` and `ratings.csv` directly in `data/`. Startup waits for the download and model fitting; subsequent startups reuse the local files. Internet is required for dependency installation and the first data download. A failed download reports how to install the CSVs manually. Existing CSVs are never downloaded again automatically.

To download ahead of time:

```sh
python -m app.download_data
```

## Deploy on Render

The included `render.yaml` defines a free Python web service in Frankfurt. Connect this GitHub repository to Render as a Blueprint to use these settings. `.python-version` selects Python 3.13. The build installs dependencies and downloads MovieLens; the service starts one Uvicorn worker on Render's assigned port. The health check calls `/api/movies/popular`, which succeeds after model initialization. The frontend and API share one URL.

For manual Web Service setup, use these commands:

```sh
# Build command
python -m pip install -r requirements.txt && python -m app.download_data
# Start command
python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1
```

Choose the Free plan, leave the root directory empty, and use `main`. Free services sleep when idle and may take time to wake up. The model is rebuilt when the process starts. No database, persistent disk, or API secrets are needed. A deployment configuration in GitHub alone does not create a running service; complete service creation in a connected Render account.

## Use the website

Search for a movie, use arrow keys and Enter to select an autocomplete result, or click a popular movie. Each recommendation can become the starting point for another search. The home page has the twelve most-rated movies, and recommendations display up to ten neighbors. Unknown or ambiguous titles show selectable suggestions. Movies without enough eligible ratings show an explanation. Back to popular returns to the home collection.

The artwork is intentionally generated with CSS typography and shapes, so every card works without external image services. Optional TMDB poster integration is not included. Google Fonts enhances typography when available; system sans-serif fonts work offline.

## How recommendations work

1. Load the catalog and ratings with pandas. Count ratings in the original dataset for the popularity list.
2. Remove movies with fewer than ten ratings and users with fewer than five ratings. Repeat until stable, so removing one group cannot leave the other below its minimum.
3. Make a movie-by-user pivot table. Each cell holds a user's rating; missing ratings become zero. Convert it to a NumPy float32 array and then a SciPy sparse matrix.
4. Fit scikit-learn `NearestNeighbors(metric="cosine", algorithm="brute")`. Two movies are similar when their rating vectors point in a similar direction: the same users tend to rate them similarly.
5. For a selected movie, retrieve nearby movies, remove the selected movie, and return `1 - cosine_distance`, clipped to 0–1. A displayed 80% match means 0.80 cosine similarity; it is **not** an 80% chance of enjoying the movie.

The model and sparse matrix are cached once per process. Neighbor queries run on demand without fitting again or storing an all-pairs similarity matrix. FastAPI executes synchronous endpoints in its thread pool. A server restart or development reload builds a fresh model; multiple worker processes each hold their own model.

`app.recommender.get_recommendations(movie_title, n=10)` is also usable directly from Python. Exact title matching ignores case and surrounding whitespace. A unique substring is accepted; multiple substring matches raise `RecommendationError(code="ambiguous_title")`. Unrecognized titles raise `unknown_title` with fuzzy suggestions. Known movies excluded from the model raise `insufficient_ratings`. `n` must be an integer from 1 through 50; fewer results are returned when fewer eligible neighbors exist.

## API

| Endpoint | Response |
| --- | --- |
| `GET /api/search?q=toy` | Up to eight title strings, ranked by original rating count |
| `GET /api/recommend?title=Toy%20Story%20(1995)&n=10` | List of `{title, genres, score}` |
| `GET /api/movies/popular` | Up to twelve `{title, genres, rating_count}` records |
| `GET /` | Frontend |

`genres` is the MovieLens pipe-separated string. Search and recommendation titles must contain non-whitespace text and be no longer than 300 characters. Invalid parameters receive HTTP 422; unknown titles receive 404. Title lookup errors have `{detail: {code, message, matches}}`. Other validation failures use FastAPI's standard validation response. Search treats query characters literally, not as regular expressions. The frontend uses text nodes for catalog content and cancels stale requests.

## Tests

```sh
python -m pytest -q
```

Tests create small synthetic CSVs, so they run offline and do not depend on changes to MovieLens. They check known nearest neighbors, ordering, self exclusion, limits, case normalization, fuzzy/ambiguous/under-rated titles, validation, literal autocomplete, popularity, cached model reuse, and API responses.

## Project layout

```text
movie-recommender/
  app/
    __init__.py
    main.py
    recommender.py
    download_data.py
    static/
      index.html
      style.css
      script.js
  data/
  tests/test_recommender.py
  requirements.txt
  README.md
```

## Data and limitations

Data: [GroupLens MovieLens](https://grouplens.org/datasets/movielens/latest/) and its [dataset README and license terms](https://files.grouplens.org/datasets/movielens/ml-latest-small-README.html). The small dataset is historical, so recent releases are generally absent. Respect the dataset's usage and redistribution terms. The downloader keeps only the two required CSVs; consult the linked README for attribution and usage conditions. `ml-latest-small` is a mutable release, so later downloads can differ.

Raw cosine similarity can favor widely rated movies. Missing ratings are treated as zeros, and this version does not normalize individual rating habits or measure shared-rater confidence. It recommends from one selected movie; a multi-rating user profile is a future extension. Development `--reload` is for local use; production should use a supervised process and appropriate HTTPS deployment.

## Ideas for improvement

- Evaluate ranking quality on held-out ratings using recall@k and NDCG.
- Add shared-rater shrinkage and mean-centered ratings to reduce noisy similarities.
- Blend multiple selected movies into a weighted taste profile.
- Combine genre or text features with collaborative filtering for sparse or new titles.
- Add server-side TMDB poster lookup with caching and API-key environment configuration.
- For larger datasets, construct sparse matrices directly and precompute top-k neighbors.
