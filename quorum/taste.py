"""Taste DNA: turn an AniList list (plus live swipes) into a feature-weight profile.

Each genre / tag gets a weight = shrunk average of "how much above/below your own mean
did you rate things with this feature". The same profile then predicts how much you
would score any unseen show, and powers compatibility between two people.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .models import Entry, Media

PRIOR_MEAN = 70.0
COMMUNITY_MEAN = 72.0
SHRINK_K = 2.0          # pseudo-observations pulling every weight toward 0
GAIN = 32.0             # affinity (-1..1) -> score points
COMMUNITY_PULL = 0.5    # how much the crowd's opinion leaks into a prediction

SWIPE_SIGNAL = {"like": 1.0, "super": 2.0, "nope": -1.2}
SWIPE_DIRECT = {"like": 8.0, "super": 18.0, "nope": -30.0}


@dataclass
class Profile:
    num: dict[str, float] = field(default_factory=dict)
    den: dict[str, float] = field(default_factory=dict)
    mean: float = PRIOR_MEAN
    n_rated: int = 0
    seen: set[int] = field(default_factory=set)
    planning: set[int] = field(default_factory=set)
    favorites: list[tuple[int, int]] = field(default_factory=list)   # (media_id, score)
    scores: dict[int, int] = field(default_factory=dict)
    crowd_delta: float = 0.0     # how much more generous than the crowd (points)
    n_features: int = 0

    # -- weights -----------------------------------------------------------
    def weight(self, feat: str) -> float:
        d = self.den.get(feat)
        if not d:
            return 0.0
        return self.num[feat] / (d + SHRINK_K)

    def weights(self) -> dict[str, float]:
        return {f: self.weight(f) for f in self.den}

    def _fold(self, media: Media, signal: float) -> None:
        for feat, strength in media.features().items():
            self.num[feat] = self.num.get(feat, 0.0) + signal * strength
            self.den[feat] = self.den.get(feat, 0.0) + strength

    def with_swipes(self, swipes: dict[int, str], lookup: dict[int, Media]) -> "Profile":
        """Return a copy that has learned from tonight's swipes (session taste)."""
        p = Profile(dict(self.num), dict(self.den), self.mean, self.n_rated, set(self.seen),
                    set(self.planning), list(self.favorites), dict(self.scores),
                    self.crowd_delta, self.n_features)
        for mid, vote in swipes.items():
            if vote in SWIPE_SIGNAL and mid in lookup:
                p._fold(lookup[mid], SWIPE_SIGNAL[vote])
        return p

    # -- prediction --------------------------------------------------------
    def affinity(self, media: Media) -> float:
        feats = media.features()
        if not feats:
            return 0.0
        tot = sum(feats.values())
        return sum(self.weight(f) * s for f, s in feats.items()) / tot

    def predict(self, media: Media) -> float:
        n = self.n_rated
        mean_eff = (self.mean * n + PRIOR_MEAN * 5) / (n + 5)
        community = media.avg if media.avg else COMMUNITY_MEAN
        pred = mean_eff + GAIN * self.affinity(media) + COMMUNITY_PULL * (community - COMMUNITY_MEAN)
        return max(5.0, min(99.0, pred))


def build_profile(entries: list[Entry]) -> Profile:
    p = Profile()
    scored = [e.score for e in entries if e.score > 0]
    if scored:
        p.mean = sum(scored) / len(scored)
    p.n_rated = len(scored)
    deltas = []
    for e in entries:
        m = e.media
        if e.status in ("COMPLETED", "CURRENT", "PAUSED", "REPEATING", "DROPPED"):
            p.seen.add(m.id)
        if e.status == "PLANNING":
            p.planning.add(m.id)
        if e.score > 0:
            p.scores[m.id] = e.score
            if e.score >= 85:
                p.favorites.append((m.id, e.score))
            if m.avg:
                deltas.append(e.score - m.avg)
        # signal strength for this entry
        if e.status == "DROPPED":
            sig = (e.score - p.mean) / 20.0 - 0.5 if e.score > 0 else -1.0
        elif e.status in ("COMPLETED", "CURRENT", "PAUSED", "REPEATING"):
            sig = (e.score - p.mean) / 20.0 if e.score > 0 else (0.3 if e.status == "COMPLETED" else 0.2)
        elif e.status == "PLANNING":
            sig = 0.1
        else:
            continue
        p._fold(m, sig)
    p.favorites.sort(key=lambda x: -x[1])
    p.crowd_delta = sum(deltas) / len(deltas) if deltas else 0.0
    p.n_features = len(p.den)
    return p


# -- DNA summary ----------------------------------------------------------
ARCHETYPES = [
    ("The Mastermind", "Mind games, moral grey zones and plot twists you saw coming (but not really).",
     {"g:Psychological", "g:Thriller", "g:Mystery", "t:Crime", "t:Conspiracy", "t:Philosophy", "t:Tragedy"}),
    ("The Dreamer", "Swords, magic and other worlds. Reality is merely the opening credits.",
     {"g:Fantasy", "g:Adventure", "t:Isekai", "t:Magic", "t:Coming of Age", "t:Swordplay"}),
    ("The Heart-Wrecker", "You came for the story and stayed for the emotional damage.",
     {"g:Drama", "g:Romance", "t:Tragedy", "t:Love Triangle", "t:Bullying", "t:Primarily Female Cast"}),
    ("The Adrenaline Junkie", "If nothing explodes or gets punched into orbit, is it even an episode?",
     {"g:Action", "g:Sports", "t:Shounen", "t:Martial Arts", "t:Super Power", "t:Tournament", "t:Mecha"}),
    ("The Cozy Philosopher", "Tea, quiet streets, and quietly devastating observations about life.",
     {"g:Slice of Life", "g:Comedy", "g:Music", "t:Iyashikei", "t:Food", "t:School Club", "t:Gag Humor"}),
    ("The Night Owl", "Lights off, volume up. Something in the dark is always watching.",
     {"g:Horror", "g:Supernatural", "t:Gore", "t:Demons", "t:Ghost", "t:Dark Fantasy", "t:Survival"}),
    ("The Star Voyager", "Spaceships, cyberpunk cities and one more existential AI.",
     {"g:Sci-Fi", "g:Mecha", "t:Space", "t:Cyberpunk", "t:Artificial Intelligence", "t:Time Manipulation"}),
]


def archetype(p: Profile) -> tuple[str, str]:
    w = p.weights()
    best, best_score = None, 0.0
    for name, blurb, feats in ARCHETYPES:
        s = sum(max(0.0, w.get(f, 0.0)) for f in feats) / math.sqrt(len(feats))
        if s > best_score:
            best, best_score = (name, blurb), s
    return best or ("The Blank Slate", "Your list is still a mystery. Rate a few shows and come back.")


def _label(f: str) -> str:
    return f.split(":", 1)[1]


def top_features(p: Profile, n: int = 6, kind: str | None = "g", min_support: float = 1.5) -> list[tuple[str, float]]:
    out = [(_label(f), w) for f, w in p.weights().items()
           if (kind is None or f.startswith(kind + ":")) and p.den.get(f, 0) >= min_support]
    out.sort(key=lambda x: -x[1])
    return out[:n]


def harshness_label(mean: float) -> str:
    if mean >= 80:
        return "Gentle Critic"
    if mean >= 72:
        return "Fair Judge"
    if mean >= 62:
        return "Tough Crowd"
    return "Merciless"


def dna_summary(p: Profile) -> dict:
    name, blurb = archetype(p)
    genres = top_features(p, 6, "g")
    tags = top_features(p, 5, "t")
    positive = sum(1 for f in p.den if p.weight(f) > 0.05)
    explorer = round(100 * positive / max(1, len(p.den)))
    return {
        "archetype": name, "blurb": blurb,
        "genres": [{"name": n, "weight": round(w, 3)} for n, w in genres],
        "tags": [{"name": n, "weight": round(w, 3)} for n, w in tags],
        "mean_score": round(p.mean, 1), "judge": harshness_label(p.mean),
        "crowd_delta": round(p.crowd_delta, 1), "explorer": explorer,
        "rated": p.n_rated, "seen": len(p.seen),
    }


# -- compatibility --------------------------------------------------------
def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    keys = set(a) & set(b)
    if not keys:
        return 0.0
    dot = sum(a[k] * b[k] for k in keys)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def pearson(a: dict[int, int], b: dict[int, int]) -> tuple[float, int]:
    shared = sorted(set(a) & set(b))
    n = len(shared)
    if n < 3:
        return 0.0, n
    xs, ys = [a[i] for i in shared], [b[i] for i in shared]
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if not sx or not sy:
        return 0.0, n
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy), n


def compatibility(a: Profile, b: Profile) -> dict:
    cos = cosine(a.weights(), b.weights())
    r, n_shared = pearson(a.scores, b.scores)
    # map [-1, 1] -> [0, 100]; rating agreement only counts when there is evidence
    taste = (cos + 1) / 2
    if n_shared >= 3:
        score = 0.55 * taste + 0.45 * ((r + 1) / 2)
    else:
        score = taste
    fav_a = {m for m, _ in a.favorites}
    fav_b = {m for m, _ in b.favorites}
    wa, wb = a.weights(), b.weights()
    common = sorted(((f, min(wa[f], wb[f])) for f in set(wa) & set(wb) if f.startswith("g:")),
                    key=lambda x: -x[1])
    clash = sorted(((f, abs(wa[f] - wb[f])) for f in set(wa) & set(wb) if f.startswith("g:")
                    and wa[f] * wb[f] < 0), key=lambda x: -x[1])
    return {
        "percent": round(100 * max(0.0, min(1.0, score))),
        "shared_favorites": sorted(fav_a & fav_b),
        "shared_rated": n_shared,
        "agreement": round(r, 2) if n_shared >= 3 else None,
        "common_ground": [_label(f) for f, v in common[:3] if v > 0],
        "friction": [_label(f) for f, _ in clash[:2]],
    }
