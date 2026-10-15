"""Download MovieLens once, extracting only the files used by the app."""
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import urlopen
from zipfile import ZipFile
import shutil
import ssl

import certifi

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_URL = "https://files.grouplens.org/datasets/movielens/ml-latest-small.zip"


def ensure_data(data_dir: Path = DATA_DIR) -> Path:
    """Reuse existing CSVs or download and safely install the official dataset."""
    data_dir = Path(data_dir)
    names = ("movies.csv", "ratings.csv", "links.csv")
    if all((data_dir / name).is_file() for name in names):
        return data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    try:
        with TemporaryDirectory(dir=data_dir) as temporary:
            stage = Path(temporary)
            context = ssl.create_default_context(cafile=certifi.where())
            with urlopen(DATA_URL, timeout=60, context=context) as response, (stage / "data.zip").open("wb") as out:
                shutil.copyfileobj(response, out)
            with ZipFile(stage / "data.zip") as archive:
                # Explicit filenames avoid arbitrary archive path extraction.
                for name in names:
                    if (data_dir / name).is_file():
                        continue
                    with archive.open(f"ml-latest-small/{name}") as source, (stage / name).open("wb") as out:
                        shutil.copyfileobj(source, out)
            for name in names:
                if (stage / name).exists():
                    (stage / name).replace(data_dir / name)
    except Exception as exc:
        raise RuntimeError("MovieLens download failed. Check your connection or place movies.csv, ratings.csv and links.csv in data/.") from exc
    return data_dir


if __name__ == "__main__":
    print(f"Dataset ready: {ensure_data()}")

