const input = document.querySelector('#search');
const suggestions = document.querySelector('#suggestions');
const grid = document.querySelector('#grid');
const status = document.querySelector('#status');
const collection = document.querySelector('.collection');
const choices = document.querySelector('#choices');
let timer, searchController, pageController, active = -1, titles = [], searchVersion = 0;

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
    const error = new Error(detail?.message || 'That request could not be completed. Please try again.');
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
function renderCards(movies) {
  grid.replaceChildren();
  for (const movie of movies) {
    const year = movie.title.match(/\((\d{4})\)\s*$/)?.[1] || '—';
    const title = movie.title.replace(/\s*\(\d{4}\)\s*$/, '');
    const card = element('button', 'card'); card.type = 'button';
    card.setAttribute('aria-label', `Find movies like ${movie.title}`);
    const art = element('div', 'art'); art.setAttribute('aria-hidden', 'true');
    const hue = [...title].reduce((sum, c) => sum + c.charCodeAt(0), 0) % 360;
    art.style.setProperty('--hue', hue);
    art.append(element('span', 'art-label', 'REELWISE / CINEMA'), element('span', 'art-title', title), element('span', 'art-bottom', `${year}   •   DISCOVER ↗`));
    const metadata = element('div', 'year'); metadata.append(element('span', '', year));
    if (typeof movie.score === 'number') {
      const match = element('span', 'match', `${Math.round(movie.score * 100)}% match`);
      match.title = 'Cosine similarity of audience ratings, not a prediction of your rating'; metadata.append(match);
    } else metadata.append(element('span', '', `${movie.rating_count} ratings`));
    const tags = element('div', 'tags');
    movie.genres.split('|').slice(0, 3).forEach(genre => tags.append(element('span', 'tag', genre)));
    card.append(art, element('h3', '', title), metadata, tags);
    card.addEventListener('click', () => load(movie.title)); grid.append(card);
  }
}
async function load(title = '') {
  cancelSearch(); pageController?.abort();
  const controller = new AbortController(); pageController = controller;
  choices.replaceChildren(); grid.replaceChildren();
  input.value = title;
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
      const button = element('button', '', match); button.addEventListener('click', () => load(match)); choices.append(button);
    }
    const retry = element('button', '', 'Try again'); retry.addEventListener('click', () => load(title)); choices.append(retry);
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
      titles.forEach((title, i) => {
        const option = element('li', '', title); option.id = `suggestion-${i}`;
        option.setAttribute('role', 'option'); option.setAttribute('aria-selected', 'false');
        option.addEventListener('mousedown', e => e.preventDefault());
        option.addEventListener('click', () => load(title)); suggestions.append(option);
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
    input.setAttribute('aria-activedescendant', `suggestion-${active}`);
    suggestions.children[active].scrollIntoView({ block: 'nearest' });
  } else if (event.key === 'Enter' && active >= 0) { event.preventDefault(); load(titles[active]); }
});
input.addEventListener('blur', closeSuggestions);
document.querySelector('#search-form').addEventListener('submit', event => {
  event.preventDefault(); const title = input.value.trim();
  if (title) load(title); else input.focus();
});
document.querySelector('#reset').addEventListener('click', () => load());
load();
