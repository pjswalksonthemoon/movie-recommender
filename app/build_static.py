"""Export the fitted Python model as a standalone GitHub Pages website."""
import json
from pathlib import Path
import shutil

import numpy as np

from .recommender import MovieRecommender, get_engine


def export_site(engine: MovieRecommender, destination: Path) -> None:
    """Export the catalog and top 50 neighbors; no individual ratings are exported."""
    destination.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).parent / "static"
    for name in ("style.css", "script.js", "static-api.js"):
        shutil.copyfile(source / name, destination / name)
    html = (source / "index.html").read_text(encoding="utf-8")
    html = html.replace('/static/', './').replace('href="/"', 'href="./"')
    html = html.replace('<script src="./script.js" defer>', '<script src="./static-api.js" defer></script><script src="./script.js" defer>')
    (destination / "index.html").write_text(html, encoding="utf-8")
    (destination / ".nojekyll").write_text("", encoding="utf-8")

    catalog = engine.movies.copy()
    catalog["rating_count"] = catalog.movieId.map(engine.counts).fillna(0).astype(int)
    catalog = catalog.sort_values(["rating_count", "title"], ascending=[False, True])
    records = catalog[["movieId", "title", "genres", "rating_count"]].to_dict("records")
    recommendations = {}
    # Batches bound the intermediate distance matrix for larger catalogs.
    for start in range(0, len(engine.movie_ids), 128):
        distances, indices = engine.model.kneighbors(
            engine.matrix[start:start + 128], n_neighbors=min(51, len(engine.movie_ids)))
        for offset, (row_distances, row_indices) in enumerate(zip(distances, indices)):
            position = start + offset
            recommendations[str(int(engine.movie_ids[position]))] = [
                [int(engine.movie_ids[index]), round(float(np.clip(1 - distance, 0, 1)), 6)]
                for distance, index in zip(row_distances, row_indices) if index != position
            ][:50]
    (destination / "movies.json").write_text(json.dumps(records, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (destination / "recommendations.json").write_text(json.dumps(recommendations, separators=(",", ":")), encoding="utf-8")
    print(f"Exported {len(records)} titles and {len(recommendations)} recommendation lists to {destination}")


if __name__ == "__main__":
    export_site(get_engine(), Path(__file__).resolve().parent.parent / "dist")
