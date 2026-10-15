# Reelwise · movie recommendations

A runnable FastAPI media-discovery app with MovieLens collaborative filtering, live TMDB movie and TV listings, AniList anime, personal accounts and saved watchlists. The frontend is plain HTML/CSS/JavaScript with no build step. TMDB listings require a server-side key; AniList and the basic MovieLens catalogue do not.

## GitHub Pages hosting

The GitHub Pages edition remains a static MovieLens preview. GitHub Actions exports the catalog and fitted nearest neighbors at build time. Live TMDB/AniList requests, accounts and watchlists require the FastAPI server and cannot run on GitHub Pages. The static page explains this and retains its local MovieLens recommendation flow.

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
python -m alembic upgrade head
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000. API documentation is at http://127.0.0.1:8000/docs. Stop with Ctrl+C. If activation is restricted on Windows, run `.venv\Scripts\python.exe -m pip install -r requirements.txt` and `.venv\Scripts\python.exe -m uvicorn app.main:app --reload` instead.

On first startup, the app downloads the official MovieLens `ml-latest-small` archive and puts `movies.csv`, `ratings.csv`, and `links.csv` directly in `data/`. Startup waits for the download and model fitting; subsequent startups reuse the local files. Internet is required for dependency installation, the first data download, and TMDB requests. A failed download reports how to install the CSVs manually.

Copy `.env.example` to `.env`. Set a TMDB API key to enable the live film and TV catalogue, full details and posters. Set a unique `SECRET_KEY` for production, and set `APP_ENV=production` so startup rejects an unchanged development secret. `DATABASE_URL` defaults to `sqlite:///./data/reelwise.db`; change it to a PostgreSQL URL for a persistent hosted database. Run `python -m alembic upgrade head` whenever migrations are added.

```text
TMDB_API_KEY=your_tmdb_api_key
SECRET_KEY=a-long-random-value
DATABASE_URL=sqlite:///./data/reelwise.db
APP_ENV=development
```

Restart after changing `.env`. Keys stay on the backend. With no TMDB key, MovieLens recommendations and AniList anime remain available, while TMDB calls return partial/limited results. Provider details cache for one hour and browse/search lists for ten minutes. Never commit `.env`.

To download ahead of time:

```sh
python -m app.download_data
```

## Optional alternative: deploy on Render

The included `render.yaml` creates a Python web service and a free PostgreSQL database. Render generates `SECRET_KEY`, connects `DATABASE_URL`, sets `APP_ENV=production`, and runs migrations on startup. Open [New Blueprint on Render](https://dashboard.render.com/blueprint/new?repo=https://github.com/pjswalksonthemoon/movie-recommender), connect the GitHub repository if prompted, enter your `TMDB_API_KEY` in the secret field, then apply the Blueprint. The frontend and API share the new `onrender.com` URL. Keep the TMDB key in Render, not in GitHub or browser code. Free Render PostgreSQL databases currently expire after 30 days; upgrade or move the database before that if the watchlists need to persist longer.

For manual Web Service setup, use these commands:

```sh
# Build command
python -m pip install -r requirements.txt && python -m app.download_data
# Start command
python -m alembic upgrade head && python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1
```

The model is rebuilt when the process starts. A deployment configuration in GitHub alone does not create a running service; complete service creation in a connected host account.

## Use the website

Browse Movies, TV or Anime with category rows and genre filters, or use live search. Details show cast, trailer, seasons and anime relations when available. Movie pages offer a plain outbound Letterboxd link; no sites are scraped. The original MovieLens recommendations and person pages remain. Register to save titles in the default Watchlist or named lists, track Plan to watch/Watching/Watched status and give a personal 1–10 rating. Session cookies are httpOnly, SameSite=Lax and Secure on HTTPS; state-changing requests require a custom header and session CSRF token.

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
| `GET /api/search?q=toy&type=all` | Unified live movie, TV and anime results with `partial` flag |
| `GET /api/browse?type=anime&category=trending&page=1` | Paginated live catalogue, optional `genre` |
| `GET /api/media/{media_id}` | Unified movie, TV or anime details |
| `GET /api/media/{media_id}/similar` | Provider recommendations, blended with MovieLens for known films |
| `GET /api/movielens/search?q=toy` | Original MovieLens title search and cards |
| `GET /api/recommend?title=Toy%20Story%20(1995)&n=10` | Enriched movie cards with a collaborative-filtering match `score` |
| `GET /api/movies/popular` | Up to twelve enriched movie cards with `rating_count` |
| `GET /api/movie/{movie_id}` | MovieLens basics combined with TMDB details, credits, trailer and certification |
| `GET /api/movie/{movie_id}/similar?n=12` | Enriched similar movie cards with match score when available |
| `GET /api/person/{person_id}` | Biography, photo and up to 24 popular movie credits |
| `POST /api/auth/register`, `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me` | Account and cookie session |
| `GET`, `POST /api/watchlists` | Personal lists |
| `GET`, `PATCH`, `DELETE /api/watchlists/{id}` | Read, rename or delete an owned list |
| `POST /api/watchlists/{id}/items` | Save a unified `media_id` |
| `PATCH`, `DELETE /api/watchlists/{id}/items/{media_id}` | Update status/rating or remove a saved title |
| `GET /` | Frontend |

All list endpoints return the same card fields: `movie_id`, `title`, `year`, `genres`, `poster_url`, `summary`, `rating` (percentage), `director: {id, name}`, and `cast: [{id, name}]`; match `score` or `rating_count` appears where relevant. Up to eight card summaries are fetched concurrently and cached in memory for an hour. Individual TMDB failures fall back to MovieLens title, year, and genres. Movie ids are MovieLens ids, mapped to TMDB through `links.csv`. Filmography returns `movie_id: null` when a TMDB movie is absent from MovieLens. Search and recommendation titles must contain non-whitespace text and be no longer than 300 characters. Invalid parameters receive HTTP 422; unknown ids and titles receive 404. Title lookup errors have `{detail: {code, message, matches}}`. Other validation failures use FastAPI's standard validation response. Search treats query characters literally, not as regular expressions. The frontend builds content with text nodes, validates image URLs, and cancels stale requests.

The footer shows “Powered by TMDB” with the TMDB logo, “Anime data from AniList”, and TMDB's required notice. Review [TMDB attribution guidance](https://developer.themoviedb.org/docs/faq) before commercial use. Movie details link to Letterboxd with `https://letterboxd.com/tmdb/{tmdb_id}` as an outbound link only.

## Tests

```sh
python -m pytest -q
```

Tests create small synthetic CSVs and mock provider responses, so they run offline. They cover nearest neighbors, MovieLens/TMDB details, AniList and TV mapping, cache and retry behavior, partial search results, auth sessions and throttling, private watchlists, validation and the static export.

## Project layout

```text
movie-recommender/
  app/
    __init__.py
    main.py
    recommender.py
    tmdb.py
    auth.py
    db.py
    watchlists.py
    media/
      models.py
      cache.py
      tmdb.py
      anilist.py
      service.py
      routes.py
    download_data.py
    static/
      index.html
      style.css
      script.js
      discovery.js
      static-api.js
    build_static.py
  migrations/
  alembic.ini
  .env.example
  data/
  tests/
    test_recommender.py
    test_movie_details.py
    test_media_accounts.py
    static-api.test.cjs
  requirements.txt
  README.md
```

## Data and limitations

Data: [GroupLens MovieLens](https://grouplens.org/datasets/movielens/latest/) and its [dataset README and license terms](https://files.grouplens.org/datasets/movielens/ml-latest-small-README.html). The small dataset is historical, so recent releases are generally absent. Respect the dataset's usage and redistribution terms. The downloader keeps `movies.csv`, `ratings.csv`, and `links.csv`; consult the linked README for attribution and usage conditions. `ml-latest-small` is a mutable release, so later downloads can differ.

Raw cosine similarity can favor widely rated movies. Missing ratings are treated as zeros, and this version does not normalize individual rating habits or measure shared-rater confidence. It recommends from one selected movie; a multi-rating user profile is a future extension. The server-side cache is per process, so horizontally scaled deployments should use a shared cache. Development `--reload` is for local use; production should use a supervised process, persistent database and HTTPS.

## Ideas for improvement

- Evaluate ranking quality on held-out ratings using recall@k and NDCG.
- Add shared-rater shrinkage and mean-centered ratings to reduce noisy similarities.
- Blend multiple selected movies into a weighted taste profile.
- Combine genre or text features with collaborative filtering for sparse or new titles.
- Prewarm the TMDB cache for the most popular titles when a Python service starts.
- Add request throttling and a shared cache if the API is exposed to higher traffic.
- For larger datasets, construct sparse matrices directly and precompute top-k neighbors.
