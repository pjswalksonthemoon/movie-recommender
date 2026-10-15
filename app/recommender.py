"""In-memory item-based collaborative filtering over MovieLens ratings."""
from difflib import get_close_matches
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from sklearn.neighbors import NearestNeighbors

from .download_data import DATA_DIR, ensure_data


class RecommendationError(ValueError):
    """A recoverable title lookup error with suggested canonical titles."""

    def __init__(self, message: str, code: str, matches: list[str] | None = None):
        super().__init__(message)
        self.code = code
        self.matches = matches or []


class MovieRecommender:
    """Load the catalog and fit one reusable cosine nearest-neighbor model."""

    def __init__(self, data_dir: Path = DATA_DIR, min_movie_ratings: int = 10, min_user_ratings: int = 5):
        if min_movie_ratings < 1 or min_user_ratings < 1:
            raise ValueError("Rating thresholds must be positive.")
        self.movies = pd.read_csv(Path(data_dir) / "movies.csv").fillna({"genres": "(no genres listed)"})
        ratings = pd.read_csv(Path(data_dir) / "ratings.csv")
        self.counts = ratings.groupby("movieId").size()
        self.titles = self.movies["title"].tolist()
        self.normalized = self.movies["title"].str.casefold()
        # Iterate to a stable core so BOTH minimums still hold after filtering.
        while not ratings.empty:
            before = len(ratings)
            movies = ratings.groupby("movieId")["rating"].transform("size")
            users = ratings.groupby("userId")["rating"].transform("size")
            ratings = ratings[(movies >= min_movie_ratings) & (users >= min_user_ratings)]
            if len(ratings) == before:
                break
        if ratings.empty:
            raise ValueError("No ratings survive the minimum movie/user thresholds.")
        pivot = ratings.pivot_table(index="movieId", columns="userId", values="rating", fill_value=0)
        self.movie_ids = pivot.index.to_numpy()
        self.positions = {int(movie_id): i for i, movie_id in enumerate(self.movie_ids)}
        self.matrix = csr_matrix(pivot.to_numpy(dtype=np.float32))
        self.model = NearestNeighbors(metric="cosine", algorithm="brute").fit(self.matrix)
        self.catalog = self.movies.set_index("movieId")

    def search(self, query: str, limit: int = 8) -> list[str]:
        """Return literal case-insensitive substring matches, most rated first."""
        candidates = self.movies[self.normalized.str.contains(query.strip().casefold(), regex=False)].copy()
        candidates["count"] = candidates.movieId.map(self.counts).fillna(0)
        return candidates.sort_values(["count", "title"], ascending=[False, True]).title.head(limit).tolist()

    def _resolve(self, title: str) -> int:
        exact = self.movies[self.normalized == title.casefold()]
        if len(exact) == 1:
            return int(exact.iloc[0].movieId)
        matches = self.search(title)
        if len(exact) > 1 or len(matches) > 1:
            raise RecommendationError("Choose a specific movie title.", "ambiguous_title", matches)
        if len(matches) == 1:
            return int(self.movies[self.movies.title == matches[0]].iloc[0].movieId)
        normalized = dict(zip(self.normalized, self.titles))
        fuzzy = get_close_matches(title.casefold(), list(normalized), n=8, cutoff=0.4)
        raise RecommendationError("We couldn't find that movie. Try one of these titles.", "unknown_title", [normalized[t] for t in fuzzy])

    def get_recommendations(self, movie_title: str, n: int = 10) -> list[dict]:
        """Return up to n other movies ranked by cosine similarity (0–1).

        Exact titles are case insensitive. Partial titles resolve only when unique;
        ambiguous, unknown and filtered titles raise RecommendationError.
        """
        if not isinstance(movie_title, str) or not movie_title.strip() or len(movie_title) > 300:
            raise ValueError("Provide a movie title between 1 and 300 characters.")
        if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= 50:
            raise ValueError("n must be an integer between 1 and 50.")
        movie_id = self._resolve(movie_title.strip())
        if movie_id not in self.positions:
            raise RecommendationError("This movie has too few eligible ratings. Try a more popular movie.", "insufficient_ratings")
        index = self.positions[movie_id]
        distances, indices = self.model.kneighbors(self.matrix[index], n_neighbors=min(n + 1, len(self.movie_ids)))
        results = []
        for distance, neighbor in zip(distances[0], indices[0]):
            if neighbor == index:
                continue
            row = self.catalog.loc[self.movie_ids[neighbor]]
            results.append({"title": row.title, "genres": row.genres, "score": round(float(np.clip(1 - distance, 0, 1)), 6)})
        return results[:n]

    def popular(self) -> list[dict]:
        """Return the twelve most-rated catalog movies and their rating counts."""
        result = self.movies.copy()
        result["rating_count"] = result.movieId.map(self.counts).fillna(0).astype(int)
        return result.sort_values(["rating_count", "title"], ascending=[False, True]).head(12)[["title", "genres", "rating_count"]].to_dict("records")


@lru_cache(maxsize=1)
def get_engine() -> MovieRecommender:
    """Download if necessary and cache one fitted engine per server process."""
    return MovieRecommender(ensure_data())


def get_recommendations(movie_title: str, n: int = 10) -> list[dict]:
    """Convenience entry point using the cached default engine."""
    return get_engine().get_recommendations(movie_title, n)
