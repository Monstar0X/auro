"""Application service: everything the bot and the Mini App API share. No Telegram, no HTTP in here."""
from __future__ import annotations

import json
import threading
import time

from . import consensus, taste
from .db import Database
from .models import Entry, Media
from .taste import Profile

SWIPE_VOTES = {"like", "nope", "super", "veto"}
SPOILER_MAX = 190   # Telegram answerCallbackQuery alert text limit is 200 chars


class QuorumError(Exception):
    """Raised with a message that is safe to show to the user."""


def _now() -> int:
    return int(time.time())


class Quorum:
    def __init__(self, db: Database, client, list_ttl_hours: int = 12):
        self.db, self.client = db, client
        self.ttl = list_ttl_hours * 3600
        self._trending: tuple[float, list[Media]] | None = None
        self._pcache: dict[int, tuple[int, Profile]] = {}
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- media
    def _store_media(self, c, items: list[Media]) -> None:
        now = _now()
        c.executemany("INSERT OR REPLACE INTO media(id,json,fetched_at) VALUES(?,?,?)",
                      [(m.id, json.dumps(m.to_dict()), now) for m in items])

    def load_media(self, ids) -> dict[int, Media]:
        ids = list(ids)
        out: dict[int, Media] = {}
        with self.db.tx() as c:
            for i in range(0, len(ids), 500):
                chunk = ids[i:i + 500]
                q = ",".join("?" * len(chunk))
                for r in c.execute(f"SELECT id,json FROM media WHERE id IN ({q})", chunk):
                    out[r["id"]] = Media.from_dict(json.loads(r["json"]))
        return out

    def trending(self) -> list[Media]:
        with self._lock:
            if self._trending and time.time() - self._trending[0] < 1800:
                return self._trending[1]
        items = self.client.trending(40)
        if items:
            with self.db.tx() as c:
                self._store_media(c, items)
            with self._lock:
                self._trending = (time.time(), items)
        return items

    def find_media(self, query: str) -> list[Media]:
        items = self.client.search(query, 5)
        if items:
            with self.db.tx() as c:
                self._store_media(c, items)
        return items

    # ---------------------------------------------------------------- users
    def ensure_user(self, tg_id: int, name: str) -> None:
        with self.db.tx() as c:
            c.execute("INSERT INTO users(tg_id,name) VALUES(?,?) ON CONFLICT(tg_id) DO UPDATE SET name=excluded.name",
                      (tg_id, name))

    def user(self, tg_id: int) -> dict | None:
        with self.db.tx() as c:
            r = c.execute("SELECT * FROM users WHERE tg_id=?", (tg_id,)).fetchone()
        return dict(r) if r else None

    def link(self, tg_id: int, name: str, anilist: str) -> int:
        anilist = anilist.strip().lstrip("@")
        if not anilist or len(anilist) > 40 or not all(ch.isalnum() or ch in "_-" for ch in anilist):
            raise QuorumError("That doesn't look like an AniList username.")
        entries = self.client.fetch_list(anilist)  # may raise AniListError (message is user-safe)
        if not entries:
            raise QuorumError("That AniList list is empty (or private). Make it public and retry.")
        with self.db.tx() as c:
            self._store_media(c, [e.media for e in entries])
            c.execute("INSERT INTO users(tg_id,name,anilist,synced_at) VALUES(?,?,?,?) "
                      "ON CONFLICT(tg_id) DO UPDATE SET name=excluded.name,anilist=excluded.anilist,synced_at=excluded.synced_at",
                      (tg_id, name, anilist, _now()))
            c.execute("DELETE FROM entries WHERE tg_id=?", (tg_id,))
            c.executemany("INSERT INTO entries VALUES(?,?,?,?,?)",
                          [(tg_id, e.media.id, e.status, e.score, e.progress) for e in entries])
        self._pcache.pop(tg_id, None)
        return len(entries)

    def forget(self, tg_id: int) -> None:
        """Delete everything we hold about a person (their list, swipes, progress, regret, profile)."""
        with self.db.tx() as c:
            for table in ("entries", "swipes", "progress", "regret", "night_members", "users"):
                c.execute(f"DELETE FROM {table} WHERE tg_id=?", (tg_id,))
        self._pcache.pop(tg_id, None)

    def entries(self, tg_id: int) -> list[Entry]:
        with self.db.tx() as c:
            rows = c.execute("SELECT media_id,status,score,progress FROM entries WHERE tg_id=?", (tg_id,)).fetchall()
        media = self.load_media(r["media_id"] for r in rows)
        return [Entry(media[r["media_id"]], r["status"], r["score"], r["progress"])
                for r in rows if r["media_id"] in media]

    def profile(self, tg_id: int) -> Profile:
        u = self.user(tg_id)
        if not u or not u["anilist"]:
            return Profile()
        cached = self._pcache.get(tg_id)
        if cached and cached[0] == u["synced_at"]:
            return cached[1]
        p = taste.build_profile(self.entries(tg_id))
        self._pcache[tg_id] = (u["synced_at"], p)
        return p

    def dna(self, tg_id: int) -> dict:
        p = self.profile(tg_id)
        if p.n_features == 0:
            raise QuorumError("No taste data yet - link your AniList with /link <username>.")
        return taste.dna_summary(p)

    def compat(self, a: int, b: int) -> dict:
        pa, pb = self.profile(a), self.profile(b)
        if not pa.n_features or not pb.n_features:
            raise QuorumError("Both people need a linked AniList (/link) for a compatibility reading.")
        out = taste.compatibility(pa, pb)
        pool = {m.id: m for m in self.trending()}
        pool.update(self.load_media(pa.planning | pb.planning))
        res = consensus.rank(list(pool.values()), {a: pa, b: pb}, {}, {}, consensus.Rules(), k=3)
        out["bridge_picks"] = [self._ser_item(r, {}) for r in res["ranking"]]
        shared_media = self.load_media([m for m, _ in pa.favorites if m in {x for x, _ in pb.favorites}])
        out["shared_favorites"] = [m.title for m in shared_media.values()]
        return out

    # ---------------------------------------------------------------- nights
    def create_night(self, chat_id: int, creator: int, creator_name: str, mood: str | None = None,
                     max_eps: int | None = None, adult: bool = False, rewatch: bool = False) -> int:
        if mood and mood not in consensus.MOODS:
            raise QuorumError("Unknown mood. Try: " + ", ".join(consensus.MOODS))
        with self.db.tx() as c:
            cur = c.execute("INSERT INTO nights(chat_id,creator,mood,max_eps,adult,rewatch,created) VALUES(?,?,?,?,?,?,?)",
                            (chat_id, creator, mood, max_eps, int(adult), int(rewatch), _now()))
            nid = cur.lastrowid
        self.join_night(nid, creator, creator_name)
        return nid

    def night(self, night_id: int) -> dict:
        with self.db.tx() as c:
            r = c.execute("SELECT * FROM nights WHERE id=?", (night_id,)).fetchone()
        if not r:
            raise QuorumError("That movie night doesn't exist (anymore).")
        return dict(r)

    def set_night_message(self, night_id: int, msg_id: int) -> None:
        with self.db.tx() as c:
            c.execute("UPDATE nights SET msg_id=? WHERE id=?", (msg_id, night_id))

    def join_night(self, night_id: int, tg_id: int, name: str) -> bool:
        n = self.night(night_id)
        if n["status"] != "open":
            raise QuorumError("This night is already decided.")
        if not self.user(tg_id):
            self.ensure_user(tg_id, name)
        with self.db.tx() as c:
            cur = c.execute("INSERT OR IGNORE INTO night_members VALUES(?,?,?)", (night_id, tg_id, name))
            return cur.rowcount > 0

    def members(self, night_id: int) -> list[dict]:
        with self.db.tx() as c:
            rows = c.execute("SELECT tg_id,name FROM night_members WHERE night_id=? ORDER BY rowid", (night_id,)).fetchall()
        out = []
        for r in rows:
            u = self.user(r["tg_id"]) or {}
            out.append({"id": r["tg_id"], "name": r["name"], "linked": bool(u.get("anilist")),
                        "anilist": u.get("anilist")})
        return out

    def votes(self, night_id: int) -> dict[int, dict[int, str]]:
        with self.db.tx() as c:
            rows = c.execute("SELECT tg_id,media_id,vote FROM swipes WHERE night_id=?", (night_id,)).fetchall()
        out: dict[int, dict[int, str]] = {}
        for r in rows:
            out.setdefault(r["tg_id"], {})[r["media_id"]] = r["vote"]
        return out

    def swipe(self, night_id: int, tg_id: int, name: str, media_id: int, vote: str) -> None:
        if vote not in SWIPE_VOTES and vote != "clear":
            raise QuorumError("Invalid vote.")
        n = self.night(night_id)
        if n["status"] != "open":
            raise QuorumError("This night is already decided.")
        self.join_night(night_id, tg_id, name)
        with self.db.tx() as c:
            if vote == "clear":
                c.execute("DELETE FROM swipes WHERE night_id=? AND tg_id=? AND media_id=?", (night_id, tg_id, media_id))
            else:
                c.execute("INSERT OR REPLACE INTO swipes VALUES(?,?,?,?,?)", (night_id, tg_id, media_id, vote, _now()))

    def toggle_like(self, night_id: int, tg_id: int, name: str, media_id: int) -> bool:
        cur = self.votes(night_id).get(tg_id, {}).get(media_id)
        if cur in ("like", "super"):
            self.swipe(night_id, tg_id, name, media_id, "clear")
            return False
        self.swipe(night_id, tg_id, name, media_id, "like")
        return True

    def regret(self, chat_id: int, ids) -> dict[int, float]:
        with self.db.tx() as c:
            rows = c.execute("SELECT tg_id,value FROM regret WHERE chat_id=?", (chat_id,)).fetchall()
        wanted = set(ids)
        return {r["tg_id"]: r["value"] for r in rows if r["tg_id"] in wanted}

    def _pool(self, base: dict[int, Profile], rules: consensus.Rules, votes) -> list[Media]:
        ids: set[int] = set()
        for p in base.values():
            ids |= p.planning
        for v in votes.values():
            ids |= set(v)
        pool = self.load_media(ids)
        ok = [m for m in pool.values() if consensus.eligible(m, base, votes, rules)]
        if len(ok) < 24:  # plan-to-watch lists too thin / overlapping: top up with what's hot
            for m in self.trending():
                pool.setdefault(m.id, m)
        return list(pool.values())

    def _context(self, night_id: int):
        n = self.night(night_id)
        members = self.members(night_id)
        base = {m["id"]: self.profile(m["id"]) for m in members}
        votes = self.votes(night_id)
        rules = consensus.Rules(n["mood"], n["max_eps"], bool(n["adult"]), bool(n["rewatch"]))
        return n, members, base, votes, rules

    def result(self, night_id: int, k: int = 8) -> dict:
        n, members, base, votes, rules = self._context(night_id)
        if not members:
            raise QuorumError("Nobody has joined yet.")
        pool = self._pool(base, rules, votes)
        res = consensus.rank(pool, base, votes, self.regret(n["chat_id"], base), rules, k=k)
        names = {m["id"]: m["name"] for m in members}
        return {"night": self._ser_night(n), "members": [dict(m, swipes=len(votes.get(m["id"], {}))) for m in members],
                "ranking": [self._ser_item(r, names) for r in res["ranking"]],
                "pool_size": res["pool_size"], "fairness": res["fairness"],
                "_raw": res, "_names": names}

    def deck(self, night_id: int, tg_id: int, limit: int = 30) -> list[dict]:
        """Cards this user hasn't swiped yet, best group candidates first."""
        n, members, base, votes, rules = self._context(night_id)
        if tg_id not in base:
            base[tg_id] = self.profile(tg_id)
        pool = self._pool(base, rules, votes)
        res = consensus.rank(pool, base, votes, self.regret(n["chat_id"], base), rules, k=200)
        mine = votes.get(tg_id, {})
        names = {m["id"]: m["name"] for m in members}
        deck = [self._ser_item(r, names, viewer=tg_id) for r in res["ranking"] if r["media"].id not in mine]
        return deck[:limit]

    def decide(self, night_id: int) -> dict:
        res = self.result(night_id, k=5)
        raw = res["_raw"]
        n = res["night"]
        if not raw["ranking"]:
            raise QuorumError("No show survives everyone's filters (vetoes, watched, episode cap). "
                              "Loosen the rules or swipe more.")
        win = raw["ranking"][0]
        old = self.regret(n["chat_id"], raw["weights"])
        new = consensus.regret_after(win, raw["best_possible"], old)
        with self.db.tx() as c:
            c.execute("UPDATE nights SET status='done', winner=?, fairness=? WHERE id=?",
                      (win["media"].id, res["fairness"], night_id))
            c.executemany("INSERT INTO regret(chat_id,tg_id,value) VALUES(?,?,?) "
                          "ON CONFLICT(chat_id,tg_id) DO UPDATE SET value=excluded.value",
                          [(n["chat_id"], uid, v) for uid, v in new.items()])
        self.set_show(n["chat_id"], win["media"])
        res["night"]["status"] = "done"
        return res

    @staticmethod
    def _ser_night(n: dict) -> dict:
        mood = consensus.MOODS.get(n["mood"] or "")
        return {"id": n["id"], "chat_id": n["chat_id"], "status": n["status"], "mood": n["mood"],
                "mood_label": f'{mood["emoji"]} {mood["label"]}' if mood else None,
                "max_eps": n["max_eps"], "winner": n["winner"], "creator": n["creator"],
                "fairness": n.get("fairness"), "rewatch": bool(n["rewatch"])}

    @staticmethod
    def _ser_item(r: dict, names: dict[int, str], viewer: int | None = None) -> dict:
        m: Media = r["media"]
        d = m.to_dict()
        d.pop("tags", None)
        d.update({
            "score": r["score"], "badge": r.get("badge"), "spread": r["spread"], "likes": r["likes"],
            "loves": r["loves"], "mood_fit": r["mood_fit"], "runtime": m.runtime_minutes,
            "per_member": [{"id": u, "name": names.get(u, str(u)), "score": s} for u, s in r["per_member"].items()],
            "sacrifice": names.get(r["lowest"]) if r["spread"] >= 20 else None,
            "airing": m.status == "RELEASING",
        })
        if viewer is not None:
            d["my_score"] = r["per_member"].get(viewer)
        return d

    # ---------------------------------------------------------------- progress & spoilers
    def set_progress(self, tg_id: int, media_id: int, ep: int) -> None:
        if ep < 0 or ep > 5000:
            raise QuorumError("Episode number out of range.")
        with self.db.tx() as c:
            c.execute("INSERT OR REPLACE INTO progress VALUES(?,?,?)", (tg_id, media_id, ep))

    def progress_for(self, tg_id: int, media_id: int) -> int | None:
        with self.db.tx() as c:
            r = c.execute("SELECT ep FROM progress WHERE tg_id=? AND media_id=?", (tg_id, media_id)).fetchone()
            if r:
                return r["ep"]
            e = c.execute("SELECT status,progress FROM entries WHERE tg_id=? AND media_id=?", (tg_id, media_id)).fetchone()
        if not e or e["status"] == "PLANNING":
            return None
        if e["status"] == "COMPLETED":
            return 99999
        return e["progress"]

    def add_spoiler(self, chat_id: int, media_id: int, ep: int, author: int, author_name: str, text: str) -> int:
        text = text.strip()
        if not text:
            raise QuorumError("Spoiler text is empty.")
        if len(text) > SPOILER_MAX:
            raise QuorumError(f"Keep it under {SPOILER_MAX} characters (Telegram's reveal pop-up limit). "
                              f"You wrote {len(text)}.")
        if ep < 1:
            raise QuorumError("Episode must be 1 or higher.")
        with self.db.tx() as c:
            return c.execute("INSERT INTO spoilers(chat_id,media_id,ep,author,author_name,text,created) VALUES(?,?,?,?,?,?,?)",
                             (chat_id, media_id, ep, author, author_name, text, _now())).lastrowid

    def spoiler(self, sid: int) -> dict | None:
        with self.db.tx() as c:
            r = c.execute("SELECT * FROM spoilers WHERE id=?", (sid,)).fetchone()
        return dict(r) if r else None

    def reveal(self, sid: int, tg_id: int, force: bool = False) -> tuple[str, str]:
        """-> (verdict, text). verdict: ok | forced | locked | unknown | gone"""
        s = self.spoiler(sid)
        if not s:
            return "gone", "That spoiler no longer exists."
        if s["author"] == tg_id:
            return "ok", s["text"]
        prog = self.progress_for(tg_id, s["media_id"])
        if prog is not None and prog >= s["ep"]:
            return "ok", s["text"]
        if force:
            return "forced", s["text"]
        if prog is None:
            return "unknown", ("I don't know how far you are. Link AniList (/link) or set /progress - "
                               "or tap the skull to reveal anyway.")
        return "locked", f"🔒 You're on episode {prog}; this spoils episode {s['ep']}."

    # ---------------------------------------------------------------- shows / airing
    def set_show(self, chat_id: int, media: Media) -> None:
        aired = (media.next_ep - 1) if media.next_ep else (media.episodes or 0)
        with self.db.tx() as c:
            self._store_media(c, [media])
            c.execute("INSERT INTO shows(chat_id,media_id,last_notified_ep) VALUES(?,?,?) "
                      "ON CONFLICT(chat_id) DO UPDATE SET media_id=excluded.media_id,last_notified_ep=excluded.last_notified_ep",
                      (chat_id, media.id, aired))

    def current_show(self, chat_id: int) -> Media | None:
        with self.db.tx() as c:
            r = c.execute("SELECT media_id FROM shows WHERE chat_id=?", (chat_id,)).fetchone()
        return self.load_media([r["media_id"]]).get(r["media_id"]) if r else None

    def due_notifications(self) -> list[dict]:
        with self.db.tx() as c:
            rows = c.execute("SELECT chat_id,media_id,last_notified_ep FROM shows").fetchall()
        out = []
        for r in rows:
            m = self.client.media(r["media_id"])
            if not m or m.status != "RELEASING":
                continue
            aired = (m.next_ep - 1) if m.next_ep else (m.episodes or 0)
            if aired > r["last_notified_ep"]:
                out.append({"chat_id": r["chat_id"], "media": m, "episode": aired})
                with self.db.tx() as c:
                    c.execute("UPDATE shows SET last_notified_ep=? WHERE chat_id=?", (aired, r["chat_id"]))
        return out
