🎬 Movie Recommender

A movie recommendation website powered by item-based collaborative filtering. Search for a movie you like and get a list of similar films, based on the rating patterns of thousands of real users.

Built with Python, FastAPI and scikit-learn, with a lightweight vanilla JavaScript front end.

Features
Smart recommendations: item-based collaborative filtering using cosine similarity
Live search: autocomplete as you type, with fuzzy matching for ambiguous titles
Popular movies: home page shows the most-rated films to get you started
Match scores: every recommendation shows how closely it matches your pick
Responsive dark UI: works on desktop and mobile
Optional posters: add a TMDB API key to show movie posters (the site works fine without one)
Tested: unit tests for the recommendation engine
How it works

The engine uses item-based collaborative filtering:

Load the MovieLens ratings and build a movie × user matrix, where each cell is the rating a user gave a movie.
Filter out movies with fewer than 10 ratings and users with fewer than 5, to reduce noise.
Compute the cosine similarity between movies. Two movies are similar if the same users tend to rate them in the same way.
When you pick a movie, the engine returns the n nearest neighbours with a similarity score.

In plain English: people who liked this movie also liked these ones.

Edge cases handled: unknown titles, ambiguous titles (fuzzy matches returned), and movies with too few ratings.

Tech stack
Layer	Technology
Backend	Python 3.11+, FastAPI
ML / data	pandas, NumPy, scikit-learn
Frontend	HTML, CSS, vanilla JavaScript
Dataset	MovieLens ml-latest-small
Testing	pytest
Project structure
movie-recommender/
├── app/
│   ├── main.py            # FastAPI app and routes
│   ├── recommender.py     # Recommendation engine
│   └── static/            # index.html, style.css, script.js
├── data/                  # Dataset downloads here on first run
├── tests/
│   └── test_recommender.py
├── requirements.txt
└── README.md
Getting started
Prerequisites
Python 3.11 or newer
pip
Installation
bash
# Clone the repository
git clone https://github.com/<your-username>/movie-recommender.git
cd movie-recommender

# Create and activate a virtual environment
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
Run the app
bash
uvicorn app.main:app --reload

Then open http://127.0.0.1:8000 in your browser. The MovieLens dataset downloads automatically on first run.

Optional: movie posters

To display posters, get a free API key from TMDB and set it as an environment variable:

bash
export TMDB_API_KEY=your_key_here     # Windows: set TMDB_API_KEY=your_key_here

Without a key, the site shows styled placeholder cards instead.

Run the tests
bash
pytest
API reference
Endpoint	Description
GET /api/search?q=toy	Autocomplete: up to 8 matching movie titles
GET /api/recommend?title=Toy Story (1995)&n=10	Returns n recommendations as {title, genres, score}
GET /api/movies/popular	Top 12 most-rated movies
GET /	Serves the front end

Example response for /api/recommend:

json
[
  { "title": "Toy Story 2 (1999)", "genres": "Adventure|Animation|Children|Comedy|Fantasy", "score": 0.87 },
  { "title": "Monsters, Inc. (2001)", "genres": "Adventure|Animation|Children|Comedy|Fantasy", "score": 0.81 }
]
Ideas for improvement
Personalised recommendations from a user's own ratings
Hybrid model combining collaborative and content-based (genre) filtering
Larger dataset (ml-25m) with a sparse-matrix pipeline
Deployment to Render, Railway or Fly.io
Movie detail pages with cast, trailers and reviews
Acknowledgements
MovieLens dataset by GroupLens Research
Movie data and posters from TMDB (optional)
Inspired by Code Heroku's Building a Movie Recommendation Engine tutorial
License

This project is licensed under the MIT License. See the LICENSE file for details.
