const input = document.querySelector('#search');
const suggestions = document.querySelector('#suggestions');
const grid = document.querySelector('#grid');
const status = document.querySelector('#status');
const collection = document.querySelector('.collection');
const choices = document.querySelector('#choices');
const homeView = document.querySelector('#home-view');
const detailView = document.querySelector('#detail-view');
const trailerDialog = document.querySelector('#trailer-dialog');
const trailerFrame = trailerDialog.querySelector('.trailer-frame');
const safeImage = value => typeof value === 'string' && /^https:\/\/image\.tmdb\.org\/t\/p\/(w\d+|original)\/[\w./-]+$/.test(value) ? value : null;
let timer, searchController, pageController, active = -1, titles = [], searchVersion = 0, homeLoaded = false;

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
async function request(url, signal) {
  if (window.reelwiseRequest) return window.reelwiseRequest(url, signal);
  const response = await fetch(url, { signal });
  const data = await response.json();
  if (!response.ok) {
    const detail = data.detail;
    const error = new Error(typeof detail === 'string' ? detail : detail?.message || 'That request could not be completed. Please try again.');
    error.matches = detail?.matches || [];
    throw error;
  }
  return data;
}
function showStatus(message, loading = false, error = false) {
  status.replaceChildren(); status.hidden = false; status.className = error ? 'error' : '';
  if (loading) status.append(element('span', 'spinner'));
  status.append(document.createTextNode(message));
  collection.setAttribute('aria-busy', String(loading));
}
function closeSuggestions() {
  suggestions.hidden = true; input.setAttribute('aria-expanded', 'false');
  input.removeAttribute('aria-activedescendant'); active = -1;
}
function cancelSearch() {
  clearTimeout(timer); searchVersion++; searchController?.abort(); closeSuggestions(); titles = [];
}
function movieGenres(movie) {
  return Array.isArray(movie.genres) ? movie.genres : String(movie.genres || '').split('|').filter(Boolean);
}
function movieYear(movie) {
  return movie.year || movie.title.match(/\((\d{4})\)\s*$/)?.[1] || '—';
}
function navigateToMovie(movieId) {
  if (!Number.isInteger(Number(movieId)) || Number(movieId) < 1) return;
  cancelSearch();
  history.pushState({ reelwise: true }, '', `#/movie/${Number(movieId)}`);
  route();
}
function renderCards(movies) {
  grid.replaceChildren();
  for (const movie of movies) {
    const year = movieYear(movie);
    const title = movie.title.replace(/\s*\(\d{4}\)\s*$/, '');
    const card = element('button', 'card'); card.type = 'button';
    card.setAttribute('aria-label', `View details for ${movie.title}`);
    const art = element('div', 'art');
    const poster = safeImage(movie.poster);
    if (poster) {
      art.classList.add('art-poster');
      const image = element('img', 'card-poster'); image.src = poster; image.alt = `Poster for ${movie.title}`; image.loading = 'lazy'; art.append(image);
    } else {
      art.setAttribute('aria-hidden', 'true');
      const hue = [...title].reduce((sum, c) => sum + c.charCodeAt(0), 0) % 360;
      art.style.setProperty('--hue', hue);
      art.append(element('span', 'art-label', 'REELWISE / CINEMA'), element('span', 'art-title', title), element('span', 'art-bottom', `${year}   •   DISCOVER ↗`));
    }
    const metadata = element('div', 'year'); metadata.append(element('span', '', year));
    if (typeof movie.score === 'number') {
      const match = element('span', 'match', `${Math.round(movie.score * 100)}% match`);
      match.title = 'Cosine similarity of audience ratings, not a prediction of your rating'; metadata.append(match);
    } else if (Number.isFinite(movie.rating_count)) metadata.append(element('span', '', `${movie.rating_count} ratings`));
    const tags = element('div', 'tags');
    movieGenres(movie).slice(0, 3).forEach(genre => tags.append(element('span', 'tag', genre)));
    card.append(art, element('h3', '', title), metadata, tags);
    card.addEventListener('click', () => movie.movie_id ? navigateToMovie(movie.movie_id) : load(movie.title));
    grid.append(card);
  }
}
async function load(title = '') {
  cancelSearch(); pageController?.abort();
  const controller = new AbortController(); pageController = controller;
  choices.replaceChildren(); grid.replaceChildren(); input.value = title;
  document.querySelector('#collection-title').textContent = title ? `Because you liked ${title}` : 'Popular movies.';
  document.querySelector('#section-label').textContent = title ? 'FOLLOW YOUR TASTE' : 'THE CROWD HAS GOOD TASTE';
  document.querySelector('#collection-note').hidden = Boolean(title);
  document.querySelector('#reset').hidden = !title;
  showStatus(title ? 'Finding your next great watch…' : 'Bringing in the crowd favorites…', true);
  try {
    const movies = await request(title ? `/api/recommend?title=${encodeURIComponent(title)}&n=10` : '/api/movies/popular', controller.signal);
    if (controller !== pageController) return;
    collection.setAttribute('aria-busy', 'false');
    if (!movies.length) { showStatus('No recommendations yet. Try another favorite.'); return; }
    status.hidden = true; renderCards(movies);
  } catch (error) {
    if (error.name === 'AbortError' || controller !== pageController) return;
    showStatus(error.message || 'Could not connect. Please try again.', false, true);
    for (const match of error.matches || []) {
      const button = element('button', '', match.title || match); button.addEventListener('click', () => match.movie_id ? navigateToMovie(match.movie_id) : load(match)); choices.append(button);
    }
    const retry = element('button', '', 'Try again'); retry.addEventListener('click', () => load(title)); choices.append(retry);
  }
}

function addTextRow(parent, label, value) {
  if (!value || (Array.isArray(value) && !value.length)) return;
  const row = element('div', 'fact'); row.append(element('span', 'fact-label', label));
  row.append(element('span', 'fact-value', Array.isArray(value) ? value.join(', ') : String(value)));
  parent.append(row);
}
function makeDetailSkeleton() {
  detailView.replaceChildren();
  const skeleton = element('section', 'detail-skeleton'); skeleton.setAttribute('aria-label', 'Loading movie details');
  skeleton.setAttribute('aria-busy', 'true');
  skeleton.append(element('div', 'skeleton skeleton-poster'), element('div', 'skeleton-copy'));
  for (let i = 0; i < 7; i++) skeleton.lastChild.append(element('span', 'skeleton skeleton-line'));
  detailView.append(skeleton);
}
function renderError(error, movieId) {
  detailView.replaceChildren();
  const panel = element('section', 'detail-error');
  panel.append(element('h1', '', 'We couldn’t load this movie'), element('p', '', error.message || 'Something went wrong. Please try again.'));
  const retry = element('button', 'search-submit', 'Try again'); retry.addEventListener('click', () => showMovie(movieId));
  panel.append(retry); detailView.append(panel);
}
function renderDetails(movie, movieId) {
  detailView.replaceChildren();
  document.title = `${movie.title} — Reelwise`;
  const wrapper = element('article', 'movie-detail page-enter');
  const hero = element('section', 'detail-hero');
  const backdrop = safeImage(movie.backdrop);
  if (backdrop) { const image = element('img', 'detail-backdrop'); image.src = backdrop; image.alt = ''; image.setAttribute('aria-hidden', 'true'); hero.append(image); }
  const content = element('div', 'detail-hero-content');
  const poster = safeImage(movie.poster);
  const posterWrap = element('div', 'detail-poster-wrap');
  if (poster) { const image = element('img', 'detail-poster'); image.src = poster; image.alt = `Poster for ${movie.title}`; posterWrap.append(image); }
  else posterWrap.append(element('div', 'detail-poster-placeholder', movie.title));
  const info = element('div', 'detail-info');
  const back = element('button', 'back-button', '← Back'); back.type = 'button';
  back.addEventListener('click', () => history.state?.reelwise ? history.back() : goHome());
  info.append(back, element('p', 'eyebrow detail-eyebrow', 'MOVIE DETAILS'));
  const title = element('h1', 'detail-title', movie.title); info.append(title);
  title.tabIndex = -1;
  const year = movie.year || movie.release_date?.slice(0, 4);
  const subtitle = [year, movie.certification, movie.runtime ? `${movie.runtime} min` : null].filter(Boolean).join('  •  ');
  if (subtitle) info.append(element('p', 'detail-subtitle', subtitle));
  if (movie.tagline) info.append(element('p', 'detail-tagline', movie.tagline));
  const genreLine = element('div', 'detail-genres');
  movieGenres(movie).forEach(genre => genreLine.append(element('span', 'genre-chip', genre)));
  if (genreLine.childElementCount) info.append(genreLine);
  const ratingRow = element('div', 'detail-rating-row');
  if (Number.isFinite(movie.vote_average)) {
    const rating = element('div', 'rating-badge', `${Math.round(movie.vote_average * 10)}%`); rating.setAttribute('aria-label', `TMDB rating ${Math.round(movie.vote_average * 10)} percent`);
    const votes = element('span', 'vote-count', `${Number(movie.vote_count || 0).toLocaleString()} votes`); ratingRow.append(rating, votes);
  }
  if (movie.trailer_key && /^[\w-]{6,20}$/.test(movie.trailer_key)) {
    const watch = element('button', 'trailer-button', '▶  Watch trailer'); watch.type = 'button';
    watch.addEventListener('click', () => openTrailer(movie.trailer_key, movie.title)); ratingRow.append(watch);
  }
  if (ratingRow.childElementCount) info.append(ratingRow);
  content.append(posterWrap, info); hero.append(content); wrapper.append(hero);

  if (movie.limited || movie.notice) {
    const notice = element('p', 'limited-notice', movie.notice || 'Limited movie information is available. Add TMDB_API_KEY to your .env file for cast, ratings, posters and trailers.');
    wrapper.append(notice);
  }
  const body = element('div', 'detail-body');
  const overview = element('section', 'detail-section'); overview.append(element('p', 'eyebrow', 'THE STORY'), element('h2', '', 'About this movie'));
  overview.append(element('p', 'overview-copy', movie.overview || 'No overview is available for this movie.')); body.append(overview);
  const facts = element('section', 'detail-section'); facts.append(element('p', 'eyebrow', 'AT A GLANCE'), element('h2', '', 'Key facts'));
  const factGrid = element('div', 'facts-grid');
  addTextRow(factGrid, 'Director', movie.directors); addTextRow(factGrid, 'Writers', movie.writers);
  addTextRow(factGrid, 'Release date', movie.release_date); addTextRow(factGrid, 'Original language', movie.original_language?.toUpperCase());
  if (factGrid.childElementCount) { facts.append(factGrid); body.append(facts); }
  if (movie.cast?.length) {
    const castSection = element('section', 'detail-section cast-section'); castSection.append(element('p', 'eyebrow', 'THE PEOPLE'), element('h2', '', 'Cast'));
    const castRow = element('div', 'cast-row');
    for (const person of movie.cast) {
      const castCard = element('article', 'cast-card'); const photo = safeImage(person.profile);
      if (photo) { const image = element('img', 'cast-photo'); image.src = photo; image.alt = `Photo of ${person.name}`; image.loading = 'lazy'; castCard.append(image); }
      else castCard.append(element('div', 'cast-placeholder', (person.name || '?').slice(0, 1).toUpperCase()));
      castCard.append(element('h3', '', person.name || 'Unknown'), element('p', '', person.character || ''));
      castRow.append(castCard);
    }
    castSection.append(castRow); body.append(castSection);
  }
  const similarSection = element('section', 'detail-section similar-section');
  similarSection.append(element('p', 'eyebrow', 'KEEP EXPLORING'), element('h2', '', 'More like this'));
  const similarStatus = element('div', 'similar-status'); similarStatus.append(element('span', 'spinner'), document.createTextNode('Finding movies you might love…'));
  const similarGrid = element('div', 'grid detail-grid'); similarGrid.setAttribute('aria-live', 'polite');
  similarSection.append(similarStatus, similarGrid); body.append(similarSection);
  wrapper.append(body); detailView.append(wrapper); title.focus({ preventScroll: true });
  loadSimilar(movieId, similarGrid, similarStatus);
}
function openTrailer(key, title) {
  trailerFrame.replaceChildren();
  const frame = document.createElement('iframe');
  frame.src = `https://www.youtube-nocookie.com/embed/${encodeURIComponent(key)}?autoplay=1`;
  frame.title = `${title} trailer`; frame.allow = 'accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share'; frame.allowFullscreen = true;
  trailerFrame.append(frame); trailerDialog.showModal();
}
trailerDialog.querySelector('.modal-close').addEventListener('click', () => trailerDialog.close());
trailerDialog.addEventListener('close', () => trailerFrame.replaceChildren());
trailerDialog.addEventListener('click', event => { if (event.target === trailerDialog) trailerDialog.close(); });
async function loadSimilar(movieId, target, state) {
  try {
    const movies = await request(`/api/movie/${movieId}/similar?n=12`, pageController?.signal);
    if (!target.isConnected) return;
    state.replaceChildren();
    if (!movies.length) { state.append(element('p', 'empty-similar', 'No similar movies are available yet.')); return; }
    for (const movie of movies) {
      const card = element('button', 'card'); card.type = 'button'; card.setAttribute('aria-label', `View details for ${movie.title}`);
      const poster = safeImage(movie.poster); const art = element('div', 'art');
      if (poster) { art.classList.add('art-poster'); const image = element('img', 'card-poster'); image.src = poster; image.alt = `Poster for ${movie.title}`; image.loading = 'lazy'; art.append(image); }
      else { const hue = [...movie.title].reduce((sum, c) => sum + c.charCodeAt(0), 0) % 360; art.style.setProperty('--hue', hue); art.setAttribute('aria-hidden', 'true'); art.append(element('span', 'art-label', 'REELWISE / CINEMA'), element('span', 'art-title', movie.title.replace(/\s*\(\d{4}\)\s*$/, '')), element('span', 'art-bottom', `${movieYear(movie)}   •   DISCOVER ↗`)); }
      const metadata = element('div', 'year'); metadata.append(element('span', '', movieYear(movie)));
      if (typeof movie.score === 'number') metadata.append(element('span', 'match', `${Math.round(movie.score * 100)}% match`));
      const tags = element('div', 'tags'); movieGenres(movie).slice(0, 3).forEach(genre => tags.append(element('span', 'tag', genre)));
      card.append(art, element('h3', '', movie.title.replace(/\s*\(\d{4}\)\s*$/, '')), metadata, tags);
      card.addEventListener('click', () => navigateToMovie(movie.movie_id || movie.id)); target.append(card);
    }
  } catch (error) {
    if (error.name === 'AbortError' || !target.isConnected) return;
    state.replaceChildren(element('span', 'similar-error', 'Similar movies could not be loaded.'), Object.assign(element('button', 'text-button', 'Retry'), { onclick: () => loadSimilar(movieId, target, state) }));
  }
}
async function showMovie(movieId) {
  cancelSearch(); pageController?.abort();
  const controller = new AbortController(); pageController = controller;
  homeView.hidden = true; detailView.hidden = false; detailView.classList.remove('page-enter');
  makeDetailSkeleton(); window.scrollTo({ top: 0, behavior: 'instant' });
  try {
    const movie = await request(`/api/movie/${movieId}`, controller.signal);
    if (controller !== pageController) return;
    renderDetails(movie, Number(movieId));
  } catch (error) {
    if (error.name === 'AbortError' || controller !== pageController) return;
    renderError(error, Number(movieId));
  }
}
function goHome() {
  if (location.hash === '#/' || !location.hash) { route(); return; }
  history.pushState({ reelwise: true }, '', '#/'); route();
}
function route() {
  const match = location.hash.match(/^#\/movie\/(\d+)\/?$/);
  if (match) showMovie(Number(match[1]));
  else {
    pageController?.abort(); detailView.hidden = true; homeView.hidden = false;
    document.title = 'Reelwise — Your next great watch';
    window.scrollTo({ top: 0, behavior: 'instant' });
    if (!homeLoaded) { homeLoaded = true; load(); }
  }
}

input.addEventListener('input', () => {
  cancelSearch(); const query = input.value.trim(); if (!query) return;
  const version = searchVersion;
  timer = setTimeout(async () => {
    searchController = new AbortController();
    try {
      titles = await request(`/api/search?q=${encodeURIComponent(query)}`, searchController.signal);
      if (version !== searchVersion) return;
      suggestions.replaceChildren(); active = -1;
      titles.forEach((movie, i) => {
        const option = element('li', '', movie.title); option.id = `suggestion-${i}`;
        option.setAttribute('role', 'option'); option.setAttribute('aria-selected', 'false');
        option.addEventListener('mousedown', e => e.preventDefault());
        option.addEventListener('click', () => navigateToMovie(movie.movie_id)); suggestions.append(option);
      });
      if (!titles.length) {
        const empty = element('li', '', 'No exact matches. Press Enter to find similar titles.');
        empty.setAttribute('role', 'presentation'); suggestions.append(empty);
      }
      suggestions.hidden = false; input.setAttribute('aria-expanded', 'true');
    } catch (error) {
      if (error.name !== 'AbortError' && version === searchVersion) {
        suggestions.replaceChildren(element('li', '', 'Search unavailable. Press Enter to retry.'));
        suggestions.hidden = false; input.setAttribute('aria-expanded', 'true');
      }
    }
  }, 250);
});
input.addEventListener('keydown', event => {
  if (event.key === 'Escape') { cancelSearch(); return; }
  if (suggestions.hidden || !titles.length) return;
  if (['ArrowDown', 'ArrowUp'].includes(event.key)) {
    event.preventDefault(); active = (active + (event.key === 'ArrowDown' ? 1 : -1) + titles.length) % titles.length;
    [...suggestions.children].forEach((option, i) => option.setAttribute('aria-selected', String(i === active)));
    input.setAttribute('aria-activedescendant', `suggestion-${active}`); suggestions.children[active].scrollIntoView({ block: 'nearest' });
  } else if (event.key === 'Enter' && active >= 0) { event.preventDefault(); navigateToMovie(titles[active].movie_id); }
});
input.addEventListener('blur', closeSuggestions);
document.querySelector('#search-form').addEventListener('submit', event => {
  event.preventDefault(); const query = input.value.trim();
  const match = titles.find(movie => movie.title.toLocaleLowerCase() === query.toLocaleLowerCase()) || (titles.length === 1 ? titles[0] : null);
  if (match) navigateToMovie(match.movie_id); else if (query) load(query); else input.focus();
});
document.querySelector('#reset').addEventListener('click', () => load());
window.addEventListener('hashchange', route);
route();

