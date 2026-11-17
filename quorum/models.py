from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Media:
    id: int
    title: str
    genres: list[str] = field(default_factory=list)
    tags: dict[str, int] = field(default_factory=dict)   # tag name -> rank 0..100
    avg: int | None = None                                # community score 0..100
    episodes: int | None = None
    duration: int | None = None                           # minutes per episode
    format: str | None = None
    status: str | None = None                             # FINISHED / RELEASING / NOT_YET_RELEASED
    adult: bool = False
    year: int | None = None
    cover: str | None = None
    color: str | None = None
    banner: str | None = None
    next_ep: int | None = None
    next_at: int | None = None                            # unix seconds

    def features(self, tag_min_rank: int = 40, max_tags: int = 8) -> dict[str, float]:
        """Feature -> strength. Genres count fully, tags count by their rank."""
        f: dict[str, float] = {f"g:{g}": 1.0 for g in self.genres}
        tags = sorted(self.tags.items(), key=lambda kv: -kv[1])
        for name, rank in [t for t in tags if t[1] >= tag_min_rank][:max_tags]:
            f[f"t:{name}"] = rank / 100.0
        return f

    @property
    def runtime_minutes(self) -> int | None:
        if self.episodes and self.duration:
            return self.episodes * self.duration
        return None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Media":
        return cls(**d)

    @classmethod
    def from_anilist(cls, m: dict[str, Any]) -> "Media":
        t = m.get("title") or {}
        nxt = m.get("nextAiringEpisode") or {}
        cov = m.get("coverImage") or {}
        return cls(
            id=int(m["id"]),
            title=t.get("english") or t.get("romaji") or f"#{m['id']}",
            genres=list(m.get("genres") or []),
            tags={x["name"]: int(x.get("rank") or 0) for x in (m.get("tags") or [])},
            avg=m.get("averageScore"),
            episodes=m.get("episodes"),
            duration=m.get("duration"),
            format=m.get("format"),
            status=m.get("status"),
            adult=bool(m.get("isAdult")),
            year=m.get("seasonYear"),
            cover=cov.get("large"),
            color=cov.get("color"),
            banner=m.get("bannerImage"),
            next_ep=nxt.get("episode"),
            next_at=nxt.get("airingAt"),
        )


@dataclass
class Entry:
    """One row of somebody's AniList list."""
    media: Media
    status: str            # COMPLETED CURRENT PLANNING PAUSED DROPPED REPEATING
    score: int = 0         # 0..100, 0 = unscored
    progress: int = 0
