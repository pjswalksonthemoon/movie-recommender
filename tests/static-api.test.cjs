const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.join(__dirname, '..', 'dist');
const context = {window: {}, document: {baseURI: 'https://example.github.io/movie-recommender/'}, URL,
  fetch: async url => ({ok: true, json: async () => JSON.parse(fs.readFileSync(path.join(root, new URL(url).pathname.split('/').pop()), 'utf8'))})};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(root, 'static-api.js'), 'utf8'), context);
const request = context.window.reelwiseRequest;

test('popular and autocomplete work under a repository subpath', async () => {
  assert.equal((await request('/api/movies/popular')).length, 12);
  const movies = await request('/api/search?q=toy');
  assert.equal(movies.length, 8);
  assert.equal(movies[0], 'Toy Story (1995)');
});
test('recommendations have expected neighbor, scores, limits, and no self match', async () => {
  const movies = await request('/api/recommend?title=Toy%20Story%20(1995)&n=10');
  assert.equal(movies.length, 10);
  assert.equal(movies[0].title, 'Toy Story 2 (1999)');
  assert(movies.every(movie => movie.title !== 'Toy Story (1995)' && movie.score >= 0 && movie.score <= 1));
  assert.equal((await request('/api/recommend?title=Toy%20Story%20(1995)&n=50')).length, 50);
});
test('ambiguous and misspelled titles return suggestions', async () => {
  await assert.rejects(request('/api/recommend?title=toy'), error => error.matches.includes('Toy Story (1995)'));
  await assert.rejects(request('/api/recommend?title=Tyo%20Story%20(1995)'), error => error.matches.includes('Toy Story (1995)'));
});
test('filtered titles and invalid inputs fail clearly', async () => {
  const movies = JSON.parse(fs.readFileSync(path.join(root, 'movies.json'), 'utf8'));
  const neighbors = JSON.parse(fs.readFileSync(path.join(root, 'recommendations.json'), 'utf8'));
  const rare = movies.find(movie => !neighbors[movie.movieId] && movies.filter(other => other.title === movie.title).length === 1);
  await assert.rejects(request(`/api/recommend?title=${encodeURIComponent(rare.title)}`), /too few/);
  await assert.rejects(request('/api/recommend?title=toy&n=0'), /between 1 and 50/);
  await assert.rejects(request('/api/search?q=%20'), /Enter a movie/);
});
test('exported HTML uses relative assets and loads adapter before frontend', () => {
  const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
  assert(!html.includes('/static/'));
  assert(!html.includes('href="/"'));
  assert(html.indexOf('./static-api.js') < html.indexOf('./script.js'));
});
