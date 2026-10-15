/* Static hosting adapter. The original FastAPI frontend does not load this file. */
(() => {
  let catalogPromise, recommendationsPromise;
  const normalize = text => text.trim().toLocaleLowerCase('en');
  async function readJSON(name) {
    const response = await fetch(new URL(name, document.baseURI));
    if (!response.ok) throw new Error('Movie data could not be loaded. Please try again.');
    return response.json();
  }
  function catalog() {
    if (!catalogPromise) catalogPromise = readJSON('movies.json').catch(error => { catalogPromise = null; throw error; });
    return catalogPromise;
  }
  function recommendations() {
    if (!recommendationsPromise) recommendationsPromise = readJSON('recommendations.json').catch(error => { recommendationsPromise = null; throw error; });
    return recommendationsPromise;
  }
  function lookupError(message, matches = []) {
    const error = new Error(message); error.matches = matches; return error;
  }
  // Levenshtein similarity supplies typo suggestions without a server.
  function similarity(left, right) {
    let row = Array.from({length: right.length + 1}, (_, i) => i);
    for (let i = 1; i <= left.length; i++) {
      const next = [i];
      for (let j = 1; j <= right.length; j++) {
        next[j] = Math.min(next[j - 1] + 1, row[j] + 1, row[j - 1] + (left[i - 1] === right[j - 1] ? 0 : 1));
      }
      row = next;
    }
    return 1 - row[right.length] / Math.max(left.length, right.length, 1);
  }
  window.reelwiseRequest = async (url, signal) => {
    signal?.throwIfAborted();
    const route = new URL(url, document.baseURI);
    const movies = await catalog();
    signal?.throwIfAborted();
    if (route.pathname === '/api/movies/popular') return movies.slice(0, 12);
    const query = normalize(route.searchParams.get(route.pathname === '/api/search' ? 'q' : 'title') || '');
    if (!query || query.length > 300) throw lookupError('Enter a movie title between 1 and 300 characters.');
    const matches = movies.filter(movie => normalize(movie.title).includes(query));
    if (route.pathname === '/api/search') return matches.slice(0, 8).map(movie => movie.title);
    if (route.pathname !== '/api/recommend') throw lookupError('Unknown request.');
    const n = Number(route.searchParams.get('n') ?? 10);
    if (!Number.isInteger(n) || n < 1 || n > 50) throw lookupError('Choose between 1 and 50 recommendations.');
    const exact = movies.filter(movie => normalize(movie.title) === query);
    let selected;
    if (exact.length === 1) selected = exact[0];
    else if (exact.length > 1 || matches.length > 1) throw lookupError('Choose a specific movie title.', matches.slice(0, 8).map(movie => movie.title));
    else if (matches.length === 1) selected = matches[0];
    else {
      const fuzzy = movies.map(movie => ({title: movie.title, score: similarity(query, normalize(movie.title))}))
        .filter(movie => movie.score >= 0.4).sort((a, b) => b.score - a.score).slice(0, 8).map(movie => movie.title);
      throw lookupError("We couldn't find that movie. Try one of these titles.", fuzzy);
    }
    const neighbors = (await recommendations())[selected.movieId];
    signal?.throwIfAborted();
    if (!neighbors) throw lookupError('This movie has too few eligible ratings. Try a more popular movie.');
    const byId = new Map(movies.map(movie => [movie.movieId, movie]));
    return neighbors.slice(0, n).map(([id, score]) => ({title: byId.get(id).title, genres: byId.get(id).genres, score}));
  };
})();
