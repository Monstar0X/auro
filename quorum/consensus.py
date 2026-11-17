"""Consensus engine: pick what a *group* should watch tonight, fairly.

For every candidate we predict each member's score, turn it into a satisfaction
u in (0, 1], and combine with a **weighted geometric mean** - i.e. maximise the
Nash product. A single miserable member drags a pick down much harder than an
average would, so nobody gets steamrolled. Members who "lost" previous nights carry
**regret** from the chat history, which raises their weight tonight: fairness is
tracked across sessions, not just within one.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

from .models import Media
from .taste import Profile, SWIPE_DIRECT

FLOOR, CEIL = 40.0, 100.0   # score range mapped onto satisfaction 0..1

MOODS: dict[str, dict] = {
    "cozy":       {"label": "Cozy",        "emoji": "🍵", "boost": {"g:Slice of Life", "g:Comedy", "t:Iyashikei", "t:Food", "t:Wholesome", "g:Music"}, "avoid": {"g:Horror", "g:Thriller", "t:Gore"}},
    "hype":       {"label": "Hype",        "emoji": "🔥", "boost": {"g:Action", "g:Sports", "t:Shounen", "t:Tournament", "t:Super Power", "t:Martial Arts", "g:Mecha"}, "avoid": {"g:Slice of Life"}},
    "mindbender": {"label": "Mind-bender", "emoji": "🧠", "boost": {"g:Psychological", "g:Mystery", "g:Thriller", "t:Time Manipulation", "t:Philosophy", "g:Sci-Fi"}, "avoid": {"g:Ecchi"}},
    "cry":        {"label": "Tearjerker",  "emoji": "😭", "boost": {"g:Drama", "g:Romance", "t:Tragedy", "t:Coming of Age", "t:Loss of Loved Ones"}, "avoid": {"g:Ecchi", "t:Gag Humor"}},
    "spooky":     {"label": "Spooky",      "emoji": "👻", "boost": {"g:Horror", "g:Supernatural", "g:Thriller", "t:Ghost", "t:Demons"}, "avoid": {"g:Slice of Life"}},
}


@dataclass
class Rules:
    mood: str | None = None
    max_eps: int | None = None
    allow_adult: bool = False
    rewatch: bool = False


def mood_fit(media: Media, mood: str | None) -> float:
    """-1 .. +1 : how well a show matches the chosen mood."""
    cfg = MOODS.get(mood or "")
    if not cfg:
        return 0.0
    feats = set(media.features())
    hit = len(feats & cfg["boost"])
    bad = len(feats & cfg["avoid"])
    return max(-1.0, min(1.0, 0.45 * hit - 0.8 * bad))


def eligible(media: Media, profiles: dict[int, Profile], votes: dict[int, dict[int, str]],
             rules: Rules) -> bool:
    if media.adult and not rules.allow_adult:
        return False
    if media.status == "NOT_YET_RELEASED":
        return False
    if rules.max_eps is not None and (not media.episodes or media.episodes > rules.max_eps):
        return False
    if not rules.rewatch and any(media.id in p.seen for p in profiles.values()):
        return False
    if any(v.get(media.id) == "veto" for v in votes.values()):
        return False
    return True


def member_score(p: Profile, media: Media, vote: str | None) -> float:
    s = p.predict(media)
    if vote in SWIPE_DIRECT:
        s += SWIPE_DIRECT[vote]
    return max(5.0, min(99.0, s))


def satisfaction(score: float) -> float:
    return max(0.02, min(1.0, (score - FLOOR) / (CEIL - FLOOR)))


def _shared_loves(media: Media, profiles: dict[int, Profile]) -> list[str]:
    out = []
    for feat in media.features():
        if all(p.weight(feat) > 0.08 for p in profiles.values()):
            out.append(feat.split(":", 1)[1])
    return out[:3]


def rank(candidates: list[Media], base: dict[int, Profile], votes: dict[int, dict[int, str]],
         regret: dict[int, float], rules: Rules, k: int = 8) -> dict:
    """Return the ranked verdict. `base` maps member id -> profile (empty profile for guests)."""
    lookup = {m.id: m for m in candidates}
    session = {uid: p.with_swipes(votes.get(uid, {}), lookup) for uid, p in base.items()}
    weights = {uid: 1.0 + 2.0 * max(0.0, min(1.0, regret.get(uid, 0.0))) for uid in base}
    wsum = sum(weights.values()) or 1.0

    pool = [m for m in candidates if eligible(m, base, votes, rules)]
    best_possible = {uid: 0.0 for uid in base}
    scored: list[dict] = []
    for m in pool:
        per = {uid: member_score(session[uid], m, votes.get(uid, {}).get(m.id)) for uid in base}
        for uid, s in per.items():
            best_possible[uid] = max(best_possible[uid], s)
        logs = sum(weights[u] * math.log(satisfaction(s)) for u, s in per.items())
        group = math.exp(logs / wsum) * 100.0
        fit = mood_fit(m, rules.mood)
        total = group + 10.0 * fit
        low_uid = min(per, key=lambda u: per[u])
        high_uid = max(per, key=lambda u: per[u])
        scored.append({"media": m, "score": round(total, 1), "per_member": {u: round(s) for u, s in per.items()},
                       "lowest": low_uid, "highest": high_uid, "spread": round(per[high_uid] - per[low_uid]),
                       "mood_fit": round(fit, 2), "loves": _shared_loves(m, session),
                       "likes": sum(1 for v in votes.values() if v.get(m.id) in ("like", "super"))})
    scored.sort(key=lambda r: (-r["score"], r["media"].id))
    top = scored[:k]
    for r in top:
        r["badge"] = _badge(r, len(base))
    return {"ranking": top, "pool_size": len(pool), "weights": weights,
            "best_possible": best_possible, "fairness": _fairness(top[0], best_possible) if top else None}


def _badge(r: dict, n_members: int) -> str:
    lo = min(r["per_member"].values())
    if n_members > 1 and lo >= 75:
        return "Crowd-pleaser"
    if n_members > 1 and r["spread"] >= 30:
        return "Bold compromise"
    if r["likes"] >= max(2, n_members):
        return "Swipe favourite"
    return "Solid pick"


def _fairness(top: dict, best_possible: dict[int, float]) -> int:
    """100 = every member gets (almost) their personal best; low = somebody is paying for the group."""
    gaps = [max(0.0, (best_possible[u] - s)) / (CEIL - FLOOR) for u, s in top["per_member"].items()]
    if not gaps:
        return 100
    spread = statistics.pstdev(gaps) if len(gaps) > 1 else 0.0
    return round(100 * max(0.0, 1.0 - 0.6 * (sum(gaps) / len(gaps)) - 0.8 * spread))


def regret_after(winner: dict, best_possible: dict[int, float], old: dict[int, float]) -> dict[int, float]:
    """New regret per member: half memory, half tonight's gap versus their personal best."""
    out = {}
    for uid, s in winner["per_member"].items():
        gap = max(0.0, min(1.0, (best_possible.get(uid, s) - s) / (CEIL - FLOOR)))
        out[uid] = round(0.5 * old.get(uid, 0.0) + 0.5 * gap, 4)
    return out
