"""Offline fixtures: a small anime catalog + deterministic demo users.

Used by QUORUM_DEMO=1 (try the whole app with no internet / no AniList) and by the tests.
"""
from __future__ import annotations

import hashlib
import time

from .models import Entry, Media

# id, title, genres, tags, community avg, episodes, minutes, status, year
_RAW = [
    (1535, "Death Note", ["Mystery", "Psychological", "Thriller", "Supernatural"], {"Philosophy": 70, "Crime": 80, "Conspiracy": 60}, 84, 37, 23, "FINISHED", 2006),
    (9253, "Steins;Gate", ["Sci-Fi", "Thriller", "Drama"], {"Time Manipulation": 95, "Time Travel": 90, "Conspiracy": 50}, 87, 24, 24, "FINISHED", 2011),
    (5114, "Fullmetal Alchemist: Brotherhood", ["Action", "Adventure", "Drama", "Fantasy"], {"Alchemy": 90, "Military": 70, "Tragedy": 50}, 91, 64, 24, "FINISHED", 2009),
    (101922, "Demon Slayer", ["Action", "Fantasy", "Supernatural"], {"Demons": 90, "Swordplay": 85, "Shounen": 70}, 83, 26, 24, "FINISHED", 2019),
    (154587, "Frieren: Beyond Journey's End", ["Adventure", "Drama", "Fantasy"], {"Elf": 80, "Coming of Age": 55, "Iyashikei": 45, "Tragedy": 40}, 91, 28, 24, "FINISHED", 2023),
    (20954, "A Silent Voice", ["Drama", "Romance"], {"Bullying": 85, "Tragedy": 60, "Coming of Age": 70}, 89, 1, 130, "FINISHED", 2016),
    (21827, "Violet Evergarden", ["Drama", "Fantasy", "Slice of Life"], {"Tragedy": 70, "Loss of Loved Ones": 75, "Iyashikei": 40}, 85, 13, 24, "FINISHED", 2018),
    (20474, "Yuru Camp", ["Slice of Life", "Comedy"], {"Iyashikei": 95, "Camping": 98, "Wholesome": 85, "Primarily Female Cast": 90}, 82, 12, 24, "FINISHED", 2018),
    (21827 + 1, "Bocchi the Rock!", ["Comedy", "Music", "Slice of Life"], {"Band": 90, "Gag Humor": 70, "Primarily Female Cast": 85}, 87, 12, 24, "FINISHED", 2022),
    (16498, "Attack on Titan", ["Action", "Drama", "Fantasy", "Mystery"], {"Tragedy": 75, "Gore": 80, "Survival": 85, "Military": 70}, 85, 25, 24, "FINISHED", 2013),
    (11061, "Hunter x Hunter (2011)", ["Action", "Adventure", "Fantasy"], {"Shounen": 90, "Super Power": 70, "Tournament": 40}, 90, 148, 23, "FINISHED", 2011),
    (30276, "One Punch Man", ["Action", "Comedy", "Sci-Fi"], {"Super Power": 95, "Parody": 80, "Gag Humor": 60}, 83, 12, 24, "FINISHED", 2015),
    (19, "Monster", ["Drama", "Mystery", "Psychological", "Thriller"], {"Crime": 90, "Philosophy": 60, "Tragedy": 50}, 88, 74, 24, "FINISHED", 2004),
    (1, "Cowboy Bebop", ["Action", "Adventure", "Sci-Fi"], {"Space": 95, "Bounty Hunter": 90, "Tragedy": 40}, 86, 26, 24, "FINISHED", 1998),
    (30, "Neon Genesis Evangelion", ["Action", "Drama", "Mecha", "Psychological", "Sci-Fi"], {"Philosophy": 70, "Mecha": 90, "Tragedy": 60}, 83, 26, 24, "FINISHED", 1995),
    (6547, "Angel Beats!", ["Comedy", "Drama", "Supernatural"], {"Afterlife": 85, "Tragedy": 60, "Ghost": 50}, 80, 13, 24, "FINISHED", 2010),
    (2904, "Code Geass R2", ["Action", "Drama", "Mecha", "Sci-Fi"], {"Military": 80, "Conspiracy": 60, "Tragedy": 50}, 87, 25, 24, "FINISHED", 2008),
    (98659, "Mob Psycho 100", ["Action", "Comedy", "Supernatural"], {"Super Power": 90, "Coming of Age": 60, "Gag Humor": 40}, 86, 12, 24, "FINISHED", 2016),
    (97940, "Made in Abyss", ["Adventure", "Drama", "Fantasy", "Mystery"], {"Survival": 70, "Tragedy": 65, "Gore": 40}, 86, 13, 25, "FINISHED", 2017),
    (14719, "JoJo's Bizarre Adventure", ["Action", "Adventure", "Supernatural"], {"Super Power": 85, "Shounen": 60, "Gag Humor": 30}, 79, 26, 23, "FINISHED", 2012),
    (21, "One Piece", ["Action", "Adventure", "Comedy", "Fantasy"], {"Shounen": 95, "Pirates": 100, "Super Power": 60}, 88, 1100, 24, "RELEASING", 1999),
    (113415, "Jujutsu Kaisen", ["Action", "Fantasy", "Supernatural"], {"Shounen": 80, "Demons": 60, "Gore": 50, "Swordplay": 30}, 85, 24, 24, "FINISHED", 2020),
    (21459, "My Hero Academia", ["Action", "Comedy", "Fantasy"], {"Super Power": 95, "Shounen": 85, "School": 70}, 78, 13, 24, "FINISHED", 2016),
    (1575, "Code Geass", ["Action", "Drama", "Mecha", "Sci-Fi"], {"Military": 80, "Conspiracy": 50}, 86, 25, 24, "FINISHED", 2006),
    (20665, "Haikyu!!", ["Comedy", "Drama", "Sports"], {"Volleyball": 100, "School Club": 80, "Coming of Age": 55}, 85, 25, 24, "FINISHED", 2014),
    (21366, "Your Lie in April", ["Drama", "Music", "Romance"], {"Tragedy": 80, "Classical Music": 90, "Loss of Loved Ones": 60}, 86, 22, 23, "FINISHED", 2014),
    (8074, "Another", ["Horror", "Mystery", "Supernatural"], {"Ghost": 85, "Gore": 70, "Survival": 40}, 74, 12, 24, "FINISHED", 2012),
    (7785, "Higurashi: When They Cry", ["Horror", "Mystery", "Psychological", "Thriller"], {"Gore": 85, "Ghost": 40}, 77, 26, 24, "FINISHED", 2006),
    (21355, "Re:ZERO", ["Drama", "Fantasy", "Psychological", "Thriller"], {"Isekai": 90, "Time Loop": 90, "Tragedy": 60}, 83, 25, 24, "FINISHED", 2016),
    (146065, "Mushoku Tensei", ["Action", "Adventure", "Drama", "Fantasy"], {"Isekai": 95, "Reincarnation": 90, "Magic": 80}, 83, 23, 24, "FINISHED", 2021),
    (50265, "Spy x Family", ["Action", "Comedy", "Slice of Life"], {"Espionage": 95, "Family Life": 90, "Wholesome": 70}, 84, 12, 24, "FINISHED", 2022),
    (140960, "Dungeon Meshi", ["Adventure", "Comedy", "Fantasy"], {"Food": 95, "Dungeon": 90, "Wholesome": 50, "Iyashikei": 30}, 87, 24, 24, "FINISHED", 2024),
    (176496, "Solo Leveling", ["Action", "Adventure", "Fantasy"], {"Shounen": 40, "Super Power": 70, "Dungeon": 80}, 83, 12, 24, "FINISHED", 2024),
    (110277, "Attack on Titan: The Final Season", ["Action", "Drama", "Fantasy", "Mystery"], {"Tragedy": 80, "War": 90, "Gore": 80}, 89, 16, 24, "FINISHED", 2020),
]


def catalog() -> list[Media]:
    out, seen = [], set()
    for mid, title, genres, tags, avg, eps, dur, status, year in _RAW:
        if mid in seen:
            continue
        seen.add(mid)
        nxt, nxt_at = (None, None)
        if status == "RELEASING":
            nxt, nxt_at = 1121, int(time.time()) + 3 * 86400
        out.append(Media(id=mid, title=title, genres=genres, tags=tags, avg=avg, episodes=eps,
                         duration=dur, format="MOVIE" if eps == 1 else "TV", status=status, year=year,
                         next_ep=nxt, next_at=nxt_at))
    return out


PERSONAS = {
    "mind":  {"g:Psychological": 1, "g:Mystery": 1, "g:Thriller": 1, "g:Sci-Fi": .6, "g:Slice of Life": -.5, "g:Sports": -.4},
    "cozy":  {"g:Slice of Life": 1, "g:Comedy": .8, "g:Music": .7, "g:Romance": .4, "g:Horror": -1, "g:Thriller": -.5},
    "hype":  {"g:Action": 1, "g:Adventure": .7, "g:Sports": .6, "g:Mecha": .5, "g:Drama": -.1, "g:Slice of Life": -.6},
    "heart": {"g:Drama": 1, "g:Romance": .8, "g:Music": .5, "g:Fantasy": .3, "g:Action": -.2, "g:Comedy": -.1},
}
_ORDER = ["mind", "cozy", "hype", "heart"]


def _h(*parts) -> int:
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)


def user_list(username: str) -> list[Entry]:
    """Deterministic demo list. `demo_<persona>` picks a persona; anything else is hashed into one."""
    name = username.lower().strip()
    persona = next((p for p in _ORDER if name.endswith(p)), _ORDER[_h(name) % len(_ORDER)])
    w = PERSONAS[persona]
    entries = []
    for m in catalog():
        roll = _h(name, m.id) % 100
        aff = sum(w.get(f, 0) for f in m.features()) / max(1, len(m.genres))
        if roll < 55:
            score = int(max(30, min(100, 68 + 28 * aff + ((m.avg or 72) - 72) * 0.3 + (roll % 9) - 4)))
            status = "DROPPED" if aff < -0.35 and roll % 3 == 0 else "COMPLETED"
            entries.append(Entry(m, status, score if status != "DROPPED" else 0, m.episodes or 0))
        elif roll < 80:
            entries.append(Entry(m, "PLANNING", 0, 0))
    return entries


class DemoClient:
    """Same surface as anilist.AniListClient, but offline."""

    def __init__(self):
        self._cat = {m.id: m for m in catalog()}

    def fetch_list(self, username: str) -> list[Entry]:
        return user_list(username)

    def trending(self, n: int = 30) -> list[Media]:
        return sorted(self._cat.values(), key=lambda m: -(m.avg or 0))[:n]

    def search(self, query: str, n: int = 5) -> list[Media]:
        q = query.lower()
        return [m for m in self._cat.values() if q in m.title.lower()][:n]

    def media(self, media_id: int) -> Media | None:
        return self._cat.get(media_id)
