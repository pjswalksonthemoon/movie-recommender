"""Offline coverage for unified providers, account sessions and private lists."""
import asyncio
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import _attempts
from app.db import Base, session_factory
from app.media.anilist import AniListProvider
from app.media.cache import AsyncProvider, ProviderError, TTLCache
from app.media.models import Media
from app.media.service import MediaService
from app.media.tmdb import TMDBProvider


def run(coro):
    return asyncio.run(coro)


def test_unified_mapping_and_cache():
    calls = []

    def respond(request):
        calls.append(request.url.path)
        if request.url.path.endswith('/genre/movie/list'):
            return httpx.Response(200, json={'genres': [{'id': 18, 'name': 'Drama'}]})
        if request.url.path.endswith('/movie/603'):
            return httpx.Response(200, json={'id': 603, 'title': 'The Matrix', 'release_date': '1999-03-31',
                'overview': 'A computer hacker discovers the world is a simulation.', 'genre_ids': [18],
                'poster_path': '/poster.jpg', 'vote_average': 8.4,
                'credits': {'crew': [{'id': 5, 'name': 'Director', 'job': 'Director'}],
                            'cast': [{'id': 6, 'name': 'Actor', 'character': 'Hero'}]}})
        return httpx.Response(404)

    async def check():
        client = httpx.AsyncClient(transport=httpx.MockTransport(respond), base_url='https://api.themoviedb.org/3')
        provider = TMDBProvider('test', client=client)
        row = {'id': 603, 'title': 'The Matrix', 'genre_ids': [18]}
        first, partial = await provider._cards([row], 'movie')
        second, _ = await provider._cards([row], 'movie')
        assert not partial and first == second
        assert first[0].id == 'tmdb:movie:603' and first[0].director_or_creators[0].name == 'Director'
        assert first[0].summary_short and first[0].rating == 84
        assert len([path for path in calls if path.endswith('/movie/603')]) == 1
        await client.aclose()
    run(check())

    anime = AniListProvider().map_media({'id': 21, 'title': {'romaji': 'One Piece', 'english': 'One Piece'},
        'startDate': {'year': 1999}, 'description': '<p>Follow the crew.</p>', 'episodes': 1000,
        'averageScore': 87, 'coverImage': {'large': 'https://s4.anilist.co/file/cover.jpg'}})
    assert anime.id == 'anilist:21' and anime.media_type == 'anime'
    assert anime.summary_short == 'Follow the crew.' and anime.episodes == 1000

    tv = TMDBProvider('test').map_media({'id': 1396, 'name': 'Breaking Bad', 'first_air_date': '2008-01-20',
        'number_of_episodes': 62, 'created_by': [{'id': 1, 'name': 'Vince Gilligan'}]}, 'tv')
    assert tv.id == 'tmdb:tv:1396' and tv.episodes == 62 and tv.director_or_creators[0].name == 'Vince Gilligan'


def test_provider_fallback_retry_and_ttl(monkeypatch):
    attempts = []
    async def no_wait(_seconds):
        return None
    monkeypatch.setattr('app.media.cache.asyncio.sleep', no_wait)
    def respond(request):
        attempts.append(request.url.path)
        return httpx.Response(429, headers={'Retry-After': '0'}, json={}) if len(attempts) == 1 else httpx.Response(200, json={'ok': True})
    async def check():
        client = httpx.AsyncClient(transport=httpx.MockTransport(respond), base_url='https://example.test')
        provider = AsyncProvider('https://example.test', client=client)
        assert await provider.request('GET', '/rate') == {'ok': True}
        assert await provider.request('GET', '/rate') == {'ok': True}
        assert len(attempts) == 2
        await client.aclose()
    run(check())
    cache = TTLCache(); cache.set('x', {'ok': 1}, 0); assert cache.get('x') is None

    class Down:
        async def search(self, *_): raise ProviderError('down')
    class Up:
        async def search(self, *_): return [Media(id='anilist:1', media_type='anime', source='anilist', source_id=1, title='Anime')]
    service = MediaService(Down(), Up(), SimpleNamespace(tmdb_ids={}))
    result = run(service.search('anime', 'all'))
    assert result['partial'] and result['items'][0].title == 'Anime'


@pytest.fixture
def client(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    monkeypatch.setenv('DATABASE_URL', url)
    monkeypatch.setenv('SECRET_KEY', 'test-secret-long-enough')
    monkeypatch.setattr(main, 'get_engine', lambda: SimpleNamespace(tmdb_ids={}))
    Base.metadata.create_all(session_factory(url).kw['bind'])
    _attempts.clear()
    with TestClient(main.app) as http:
        class FakeMedia:
            async def close(self):
                pass
            async def details(self, id):
                source, media_type, source_id = ('anilist', 'anime', 21) if id.startswith('anilist:') else ('tmdb', 'movie', 603)
                return Media(id=id, media_type=media_type, source=source, source_id=source_id, title='A film')
        http.app.state.media = FakeMedia()
        yield http
    session_factory.cache_clear()


def register(client, email='a@example.com', username='alpha'):
    return client.post('/api/auth/register', headers={'X-Reelwise-Request': '1'},
                       json={'email': email, 'username': username, 'password': 'password123'})


def csrf(client):
    return {'X-Reelwise-Request': '1', 'X-CSRF-Token': client.get('/api/auth/me').json()['csrf_token']}


def test_auth_and_watchlists(client):
    assert client.get('/api/watchlists').status_code == 401
    created = register(client)
    assert created.status_code == 201 and 'httponly' in created.headers['set-cookie'].lower()
    assert 'samesite=lax' in created.headers['set-cookie'].lower()
    assert register(client).status_code == 409
    headers = csrf(client)
    lists = client.get('/api/watchlists').json(); assert len(lists) == 1
    first = lists[0]['id']
    assert client.post(f'/api/watchlists/{first}/items', json={'media_id': 'anilist:21'}).status_code == 403
    added = client.post(f'/api/watchlists/{first}/items', headers=headers, json={'media_id': 'anilist:21'})
    assert added.status_code == 201
    assert client.post(f'/api/watchlists/{first}/items', headers=headers, json={'media_id': 'anilist:21'}).status_code == 409
    updated = client.patch(f'/api/watchlists/{first}/items/anilist:21', headers=headers,
                           json={'status': 'Watched', 'rating': 9})
    assert updated.status_code == 200 and updated.json()['rating'] == 9
    second = client.post('/api/watchlists', headers=headers, json={'name': 'Weekend'}).json()
    assert second['name'] == 'Weekend'
    assert client.delete(f'/api/watchlists/{first}/items/anilist:21', headers=headers).status_code == 200
    assert client.post('/api/auth/logout', headers=headers).status_code == 200
    assert client.get('/api/watchlists').status_code == 401
    assert client.post('/api/auth/login', headers={'X-Reelwise-Request': '1'}, json={'email': 'a@example.com', 'password': 'wrong'}).status_code == 401
    assert client.post('/api/auth/login', headers={'X-Reelwise-Request': '1'}, json={'email': 'a@example.com', 'password': 'password123'}).status_code == 200
    assert len(client.get('/api/watchlists').json()) == 2


def test_rate_limit_and_ownership(client):
    for _ in range(5):
        assert client.post('/api/auth/login', headers={'X-Reelwise-Request': '1'}, json={'email': 'missing@example.com', 'password': 'wrong'}).status_code == 401
    assert client.post('/api/auth/login', headers={'X-Reelwise-Request': '1'}, json={'email': 'missing@example.com', 'password': 'wrong'}).status_code == 429
    _attempts.clear()
    register(client)
    list_id = client.get('/api/watchlists').json()[0]['id']
    register(client, 'b@example.com', 'bravo')
    assert client.get(f'/api/watchlists/{list_id}').status_code == 404
    assert client.delete(f'/api/watchlists/{list_id}', headers=csrf(client)).status_code == 404
