"""AniList GraphQL anime catalogue, respecting its response rate-limit headers."""
from __future__ import annotations

from html import unescape
from html.parser import HTMLParser
from typing import Any

from .cache import AsyncProvider, ProviderError
from .models import Credit, Media, Relation
from ..tmdb import short_overview

FIELDS = """
id title { romaji english } format status description(asHtml: false)
startDate { year } season seasonYear episodes genres tags { name rank }
coverImage { large extraLarge } bannerImage averageScore
trailer { id site } studios(isMain: true) { nodes { name } }
previewCharacters: characters(perPage: 3, sort: ROLE) {
  edges { node { id name { full } image { medium } siteUrl }
          voiceActors(language: JAPANESE) { id name { full } image { medium } siteUrl } }
}
"""
PAGE_QUERY = f"""
query($page: Int, $search: String, $sort: [MediaSort], $genre: String) {{
  Page(page: $page, perPage: 12) {{
    pageInfo {{ hasNextPage }}
    media(type: ANIME, search: $search, sort: $sort, genre: $genre) {{ {FIELDS} }}
  }}
}}
"""
DETAIL_QUERY = f"""
query($id: Int) {{
  Media(id: $id, type: ANIME) {{
    {FIELDS}
    relations {{ edges {{ relationType node {{ id title {{ romaji english }} coverImage {{ large }} }} }} }}
    recommendations(perPage: 12) {{
      nodes {{ mediaRecommendation {{ {FIELDS} }} }}
    }}
    characters(perPage: 12, sort: ROLE) {{
      edges {{ node {{ id name {{ full }} image {{ medium }} siteUrl }}
               voiceActors(language: JAPANESE) {{ id name {{ full }} image {{ medium }} siteUrl }} }}
    }}
  }}
}}
"""


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str):
        self.parts.append(data)

    def handle_starttag(self, tag: str, attrs):
        if tag in {"br", "p"}:
            self.parts.append(" ")


def plain_text(value: Any) -> str:
    parser = _TextExtractor()
    parser.feed(str(value or ""))
    return " ".join(unescape("".join(parser.parts)).split())


class AniListProvider(AsyncProvider):
    def __init__(self, **kwargs):
        # AniList currently documents a temporary 30/min limit; headers can extend the wait.
        super().__init__("https://graphql.anilist.co", min_interval=2.1, **kwargs)

    async def _query(self, query: str, variables: dict, ttl: int) -> dict:
        payload = await self.request("POST", "/", body={"query": query, "variables": variables}, ttl=ttl)
        if payload.get("errors"):
            raise ProviderError("AniList could not complete the request.")
        return payload.get("data") or {}

    def map_media(self, row: dict, *, full: bool = False) -> Media:
        title = row.get("title") or {}
        title = title if isinstance(title, dict) else {}
        name = title.get("romaji") or title.get("english") or "Untitled anime"
        year = (row.get("startDate") or {}).get("year")
        chars = ((row.get("characters") if full else row.get("previewCharacters")) or {}).get("edges") or []
        cast = []
        for edge in chars[:12 if full else 3]:
            if not isinstance(edge, dict):
                continue
            character = edge.get("node") or {}
            actors = edge.get("voiceActors") or []
            actor = next((person for person in actors if isinstance(person, dict)), None)
            if actor:
                cast.append(Credit(id=actor.get("id"), name=(actor.get("name") or {}).get("full") or "Voice actor",
                                   character=(character.get("name") or {}).get("full"),
                                   photo_url=(actor.get("image") or {}).get("medium"),
                                   external_url=actor.get("siteUrl") or f"https://anilist.co/staff/{actor.get('id')}"))
            elif character.get("id"):
                cast.append(Credit(id=character["id"], name=(character.get("name") or {}).get("full") or "Character",
                                   photo_url=(character.get("image") or {}).get("medium"),
                                   external_url=character.get("siteUrl") or f"https://anilist.co/character/{character['id']}"))
        trailer = row.get("trailer") or {}
        relations = []
        for edge in (row.get("relations") or {}).get("edges") or []:
            node = edge.get("node") or {}
            if node.get("id"):
                relations.append(Relation(id=f"anilist:{node['id']}",
                                          title=(node.get("title") or {}).get("romaji") or "Related anime",
                                          relation=str(edge.get("relationType") or "").replace("_", " ").title(),
                                          poster_url=(node.get("coverImage") or {}).get("large")))
        overview = plain_text(row.get("description"))
        studios = (row.get("studios") or {}).get("nodes") or []
        studio = studios[0].get("name") if studios and isinstance(studios[0], dict) else None
        tags = [item["name"] for item in (row.get("tags") or [])[:8]
                if isinstance(item, dict) and item.get("name")]
        episodes = row.get("episodes")
        return Media(
            id=f"anilist:{row['id']}", media_type="anime", source="anilist", source_id=row["id"],
            title=name, english_title=title.get("english"),
            year=str(year) if year else None, genres=row.get("genres") or [],
            poster_url=(row.get("coverImage") or {}).get("extraLarge") or (row.get("coverImage") or {}).get("large"),
            backdrop_url=row.get("bannerImage"), summary_short=short_overview(overview),
            overview=overview, rating=row.get("averageScore"), runtime_or_episodes=episodes,
            episodes=episodes, status=str(row.get("status") or "").replace("_", " ").title() or None,
            format=row.get("format"), studio=studio,
            director_or_creators=[Credit(name=studio)] if studio else [],
            tags=tags, cast=cast, relations=relations,
            trailer_key=trailer.get("id") if trailer.get("site") == "youtube" else None,
        )

    async def search(self, query: str) -> list[Media]:
        data = await self._query(PAGE_QUERY, {"page": 1, "search": query, "sort": None, "genre": None}, 600)
        rows = (data.get("Page") or {}).get("media") or []
        return [self.map_media(row) for row in rows if isinstance(row, dict) and row.get("id")]

    async def browse(self, category: str, genre: str | None, page: int) -> tuple[list[Media], bool]:
        sort = {"trending": "TRENDING_DESC", "popular": "POPULARITY_DESC",
                "top_rated": "SCORE_DESC", "new": "START_DATE_DESC"}[category]
        data = await self._query(PAGE_QUERY, {"page": page, "search": None, "sort": [sort], "genre": genre}, 600)
        page_data = data.get("Page") or {}
        rows = page_data.get("media") or []
        return [self.map_media(row) for row in rows if isinstance(row, dict) and row.get("id")], bool((page_data.get("pageInfo") or {}).get("hasNextPage"))

    async def details(self, source_id: int) -> Media:
        data = await self._query(DETAIL_QUERY, {"id": source_id}, 3600)
        row = data.get("Media")
        if not isinstance(row, dict):
            raise ProviderError("Anime not found.", 404)
        return self.map_media(row, full=True)

    async def similar(self, source_id: int) -> list[Media]:
        data = await self._query(DETAIL_QUERY, {"id": source_id}, 3600)
        nodes = ((data.get("Media") or {}).get("recommendations") or {}).get("nodes") or []
        return [self.map_media(node["mediaRecommendation"]) for node in nodes
                if isinstance(node, dict) and isinstance(node.get("mediaRecommendation"), dict)
                and node["mediaRecommendation"].get("id")]
