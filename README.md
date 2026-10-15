# Reelwise · movie recommendations

A runnable FastAPI app with an in-memory, item-based collaborative filtering engine, TMDB movie and person details, and a responsive HTML/CSS/JavaScript frontend. No database or frontend build is needed. The app works without a TMDB key using the basic MovieLens catalog.

## GitHub Pages hosting

The GitHub Pages edition runs entirely in the browser. GitHub Actions runs the Python recommendation engine at build time and exports the catalog plus the top 50 neighbors for every eligible movie. Search, fuzzy title suggestions, popular movies, recommendations, and linkable MovieLens-only detail pages then run in the browser. Pages cannot securely access a private TMDB API key or the FastAPI routes, so posters, summaries, person links and profiles, cast, trailers, TMDB ratings, and TMDB-based fallback recommendations are available when the FastAPI app runs with a key. The Pages cards retain their styled poster fallback.

To enable publication, open this repository's **Settings → Pages → Build and deployment → Source** and select **GitHub Actions**. The `Deploy GitHub Pages` workflow builds and publishes on pushes to `main`; it can also be run manually from Actions. The expected URL is `https://pjswalksonthemoon.github.io/movie-recommender/` after deployment succeeds.

Generate and preview the static version locally:

```sh
python -m app.build_static
node --test tests/static-api.test.cjs
python -m http.server 8080 --directory dist
```

Open http://localhost:8080. The export has relative URLs and also works beneath a repository subpath. No server or API key is needed for the hosted edition. Only movie metadata, aggregate rating counts, and derived similarity scores are exported; individual users' ratings are not published. Recommendations refresh when the workflow rebuilds. The browser uses edit-distance typo matching, while the Python API uses difflib. The `/api/*` HTTP routes are only available when running FastAPI, not on GitHub Pages.

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

On first startup, the app downloads the official MovieLens `ml-latest-small` archive and puts `movies.csv`, `ratings.csv`, and `links.csv` directly in `data/`. Startup waits for the download and model fitting; subsequent startups reuse the local files. Internet is required for dependency installation, the first data download, and TMDB requests. A failed download reports how to install the CSVs manually.

To enable posters, card summaries, and full movie and person details, copy `.env.example` to `.env` and add your TMDB API key:

```text
TMDB_API_KEY=your_tmdb_api_key
```

Restart the server after editing `.env`. The key is read only by Python and is never included in a response or sent to the browser. Without it, detail pages show the MovieLens title, year, and genres with a limited information notice. TMDB results are cached in process memory for one hour. The key can also be set as an environment variable on a Python hosting service. Never add a real `.env` file to Git.

To download ahead of time:

```sh
python -m app.download_data
```

## Optional alternative: deploy on Render

The included `render.yaml` defines a free Python web service in Frankfurt. Connect this GitHub repository to Render as a Blueprint to use these settings. `.python-version` selects Python 3.13. The build installs dependencies and downloads MovieLens; the service starts one Uvicorn worker on Render's assigned port. The health check calls `/api/movies/popular`, which succeeds after model initialization. The frontend and API share one URL.

For manual Web Service setup, use these commands:

```sh
# Build command
python -m pip install -r requirements.txt && python -m app.download_data
# Start command
python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1
```

Choose the Free plan, leave the root directory empty, and use `main`. Free services sleep when idle and may take time to wake up. The model is rebuilt when the process starts. No database or persistent disk is needed. Add `TMDB_API_KEY` in the Render service's environment variables to enable full movie details; it remains optional. A deployment configuration in GitHub alone does not create a running service; complete service creation in a connected Render account.

## Use the website

Search for a movie, use arrow keys and Enter to select an autocomplete result, or click any movie card. The hash URL opens a linkable details page. Scroll down to see credits, cast, trailer, and similar movies; selecting a similar movie opens its details and browser Back returns to the previous movie. With a TMDB key, cards show posters, short summaries, genres, rating, director, and three leading actors. Actor, director, and writer links open a person biography and up to 24 popular movie credits. MovieLens titles link back into Reelwise; other filmography titles open TMDB in a new tab. The home page has the twelve most-rated movies, and recommendations display up to ten neighbors. Unknown or ambiguous titles show selectable suggestions. Movies without enough eligible ratings use TMDB's similar movie list when available.

Cards use lazy-loaded TMDB posters when available and retain a CSS artwork fallback. The reserved 2:3 poster space prevents layout jumps. Google Fonts enhances typography when available; system sans-serif fonts work offline.

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
| `GET /api/search?q=toy` | Up to eight enriched movie cards, ranked by original rating count |
| `GET /api/recommend?title=Toy%20Story%20(1995)&n=10` | Enriched movie cards with a collaborative-filtering match `score` |
| `GET /api/movies/popular` | Up to twelve enriched movie cards with `rating_count` |
| `GET /api/movie/{movie_id}` | MovieLens basics combined with TMDB details, credits, trailer and certification |
| `GET /api/movie/{movie_id}/similar?n=12` | Enriched similar movie cards with match score when available |
| `GET /api/person/{person_id}` | Biography, photo and up to 24 popular movie credits |
| `GET /` | Frontend |

All list endpoints return the same card fields: `movie_id`, `title`, `year`, `genres`, `poster_url`, `summary`, `rating` (percentage), `director: {id, name}`, and `cast: [{id, name}]`; match `score` or `rating_count` appears where relevant. Up to eight card summaries are fetched concurrently and cached in memory for an hour. Individual TMDB failures fall back to MovieLens title, year, and genres. Movie ids are MovieLens ids, mapped to TMDB through `links.csv`. Filmography returns `movie_id: null` when a TMDB movie is absent from MovieLens. Search and recommendation titles must contain non-whitespace text and be no longer than 300 characters. Invalid parameters receive HTTP 422; unknown ids and titles receive 404. Title lookup errors have `{detail: {code, message, matches}}`. Other validation failures use FastAPI's standard validation response. Search treats query characters literally, not as regular expressions. The frontend builds content with text nodes, validates image URLs, and cancels stale requests.

The footer shows the approved TMDB logo and attribution. It also includes TMDB's required notice: “This website uses TMDB and the TMDB APIs but is not endorsed, certified, or otherwise approved by TMDB.” Review the [TMDB attribution guidance](https://developer.themoviedb.org/docs/faq) before using this project commercially.

## Tests

```sh
python -m pytest -q
```

Tests create small synthetic CSVs and mock TMDB responses, so they run offline and do not depend on live services. They check nearest neighbors, MovieLens-to-TMDB details mapping, card summary truncation and caching, person filmography, missing fields, API failures, missing-key behavior, fallback recommendations, validation, and frontend static export behavior.

## Project layout

```text
movie-recommender/
  app/
    __init__.py
    main.py
    recommender.py
    tmdb.py
    download_data.py
    static/
      index.html
      style.css
      script.js
      static-api.js
    build_static.py
  .env.example
  data/
  tests/
    test_recommender.py
    test_movie_details.py
    static-api.test.cjs
  requirements.txt
  README.md
```

## Data and limitations

Data: [GroupLens MovieLens](https://grouplens.org/datasets/movielens/latest/) and its [dataset README and license terms](https://files.grouplens.org/datasets/movielens/ml-latest-small-README.html). The small dataset is historical, so recent releases are generally absent. Respect the dataset's usage and redistribution terms. The downloader keeps `movies.csv`, `ratings.csv`, and `links.csv`; consult the linked README for attribution and usage conditions. `ml-latest-small` is a mutable release, so later downloads can differ.

Raw cosine similarity can favor widely rated movies. Missing ratings are treated as zeros, and this version does not normalize individual rating habits or measure shared-rater confidence. It recommends from one selected movie; a multi-rating user profile is a future extension. Development `--reload` is for local use; production should use a supervised process and appropriate HTTPS deployment.

## Ideas for improvement

- Evaluate ranking quality on held-out ratings using recall@k and NDCG.
- Add shared-rater shrinkage and mean-centered ratings to reduce noisy similarities.
- Blend multiple selected movies into a weighted taste profile.
- Combine genre or text features with collaborative filtering for sparse or new titles.
- Prewarm the TMDB cache for the most popular titles when a Python service starts.
- Add request throttling and a shared cache if the API is exposed to higher traffic.
- For larger datasets, construct sparse matrices directly and precompute top-k neighbors.
