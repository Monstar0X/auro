from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  tg_id INTEGER PRIMARY KEY, name TEXT, anilist TEXT, synced_at INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS media(id INTEGER PRIMARY KEY, json TEXT NOT NULL, fetched_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS entries(
  tg_id INTEGER, media_id INTEGER, status TEXT, score INTEGER, progress INTEGER,
  PRIMARY KEY(tg_id, media_id));
CREATE TABLE IF NOT EXISTS nights(
  id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, creator INTEGER, mood TEXT,
  max_eps INTEGER, adult INTEGER DEFAULT 0, rewatch INTEGER DEFAULT 0,
  status TEXT DEFAULT 'open', msg_id INTEGER, winner INTEGER, fairness INTEGER, created INTEGER);
CREATE TABLE IF NOT EXISTS night_members(
  night_id INTEGER, tg_id INTEGER, name TEXT, PRIMARY KEY(night_id, tg_id));
CREATE TABLE IF NOT EXISTS swipes(
  night_id INTEGER, tg_id INTEGER, media_id INTEGER, vote TEXT, ts INTEGER,
  PRIMARY KEY(night_id, tg_id, media_id));
CREATE TABLE IF NOT EXISTS regret(
  chat_id INTEGER, tg_id INTEGER, value REAL DEFAULT 0, PRIMARY KEY(chat_id, tg_id));
CREATE TABLE IF NOT EXISTS progress(
  tg_id INTEGER, media_id INTEGER, ep INTEGER, PRIMARY KEY(tg_id, media_id));
CREATE TABLE IF NOT EXISTS spoilers(
  id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, media_id INTEGER, ep INTEGER,
  author INTEGER, author_name TEXT, text TEXT, created INTEGER);
CREATE TABLE IF NOT EXISTS shows(
  chat_id INTEGER PRIMARY KEY, media_id INTEGER, last_notified_ep INTEGER DEFAULT 0);
"""


class Database:
    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._shared: sqlite3.Connection | None = None
        if path == ":memory:":  # tests: one shared connection
            self._shared = sqlite3.connect(":memory:", check_same_thread=False)
            self._shared.row_factory = sqlite3.Row
        with self.tx() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def tx(self):
        if self._shared is not None:
            try:
                yield self._shared
                self._shared.commit()
            except Exception:
                self._shared.rollback()
                raise
            return
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
