"""Minimal AniList GraphQL client (stdlib only). Public lists need no auth."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from .models import Entry, Media

FRAG = ("fragment M on Media{id title{romaji english} genres tags{name rank} averageScore episodes "
        "duration format status isAdult seasonYear coverImage{large color} bannerImage "
        "nextAiringEpisode{episode airingAt}}")

LIST_Q = ("query($u:String){MediaListCollection(userName:$u,type:ANIME){lists{entries{status "
          "score(format:POINT_100) progress media{...M}}}}}" + FRAG)
TRENDING_Q = ("query($n:Int){Page(page:1,perPage:$n){media(type:ANIME,sort:TRENDING_DESC,isAdult:false)"
              "{...M}}}" + FRAG)
POPULAR_Q = ("query($n:Int){Page(page:1,perPage:$n){media(type:ANIME,sort:POPULARITY_DESC,isAdult:false)"
             "{...M}}}" + FRAG)
SEARCH_Q = ("query($q:String,$n:Int){Page(page:1,perPage:$n){media(search:$q,type:ANIME,sort:SEARCH_MATCH)"
            "{...M}}}" + FRAG)
MEDIA_Q = "query($id:Int){Media(id:$id,type:ANIME){...M}}" + FRAG


class AniListError(Exception):
    pass


class AniListClient:
    def __init__(self, url: str = "https://graphql.anilist.co", timeout: int = 20):
        self.url, self.timeout = url, timeout

    def _post(self, query: str, variables: dict, retry: bool = True) -> dict:
        body = json.dumps({"query": query, "variables": variables}).encode()
        req = urllib.request.Request(self.url, data=body, headers={
            "Content-Type": "application/json", "Accept": "application/json",
            "User-Agent": "Quorum/1.0 (telegram bot)"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429 and retry:
                time.sleep(min(int(e.headers.get("Retry-After", "5")), 30))
                return self._post(query, variables, retry=False)
            if e.code == 404:
                raise AniListError("AniList user not found (or the profile is private).") from e
            if e.code == 400:  # AniList answers 400 with an errors[] body for private/missing users
                try:
                    msg = json.loads(e.read().decode())["errors"][0]["message"]
                except Exception:
                    msg = "bad request"
                raise AniListError(msg) from e
            raise AniListError(f"AniList HTTP {e.code}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise AniListError("Could not reach AniList right now.") from e
        if data.get("errors"):
            raise AniListError(data["errors"][0].get("message", "AniList error"))
        return data["data"]

    def fetch_list(self, username: str) -> list[Entry]:
        data = self._post(LIST_Q, {"u": username})
        entries, seen = [], set()
        for lst in (data["MediaListCollection"] or {}).get("lists") or []:
            for e in lst["entries"]:
                m = Media.from_anilist(e["media"])
                if m.id in seen:
                    continue
                seen.add(m.id)
                entries.append(Entry(m, e["status"], int(e.get("score") or 0), int(e.get("progress") or 0)))
        return entries

    def trending(self, n: int = 30) -> list[Media]:
        try:
            media = self._post(TRENDING_Q, {"n": n})["Page"]["media"]
            media += self._post(POPULAR_Q, {"n": n})["Page"]["media"]
        except AniListError:
            return []
        out, seen = [], set()
        for m in media:
            if m["id"] not in seen:
                seen.add(m["id"])
                out.append(Media.from_anilist(m))
        return out

    def search(self, query: str, n: int = 5) -> list[Media]:
        try:
            return [Media.from_anilist(m) for m in self._post(SEARCH_Q, {"q": query, "n": n})["Page"]["media"]]
        except AniListError:
            return []

    def media(self, media_id: int) -> Media | None:
        try:
            return Media.from_anilist(self._post(MEDIA_Q, {"id": media_id})["Media"])
        except AniListError:
            return None
