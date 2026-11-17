"""Entrypoint: runs the Mini App/API server and (if BOT_TOKEN is set) the Telegram bot in one process."""
from __future__ import annotations

import asyncio
import logging
import threading

from quorum import config, server
from quorum.anilist import AniListClient
from quorum.db import Database
from quorum.demo import DemoClient
from quorum.service import Quorum

log = logging.getLogger("quorum")


def build():
    s = config.load()
    client = DemoClient() if s.demo else AniListClient(s.anilist_url)
    return s, Quorum(Database(s.db_path), client, s.list_ttl_hours)


def seed_demo(svc: Quorum) -> None:
    """Local preview: three demo friends and an open night #1 (open /?dev=1:Alice&night=1)."""
    for uid, name, al in ((1, "Alice", "demo_mind"), (2, "Ben", "demo_cozy"), (3, "Chika", "demo_hype")):
        svc.link(uid, name, al)
    try:
        svc.night(1)
    except Exception:
        nid = svc.create_night(-1, 1, "Alice", mood=None)
        svc.join_night(nid, 2, "Ben")
        svc.join_night(nid, 3, "Chika")
    log.info("Demo ready -> http://localhost:%s/?dev=1:Alice&night=1", config.load().port)


async def amain() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    s, svc = build()
    httpd = server.serve(s, svc)
    threading.Thread(target=httpd.serve_forever, daemon=True, name="http").start()
    log.info("Mini App server on :%s (demo=%s)", s.port, s.demo)
    if s.demo and s.dev_auth:
        seed_demo(svc)
    if not (s.bot_token and s.api_id and s.api_hash):
        log.warning("BOT_TOKEN / API_ID / API_HASH not set - serving the Mini App only.")
        await asyncio.Event().wait()
        return

    from pyrogram import Client, idle  # imported late so the server/tests work without Kurigram installed
    from quorum import bot

    app = Client("quorum", api_id=s.api_id, api_hash=s.api_hash, bot_token=s.bot_token, in_memory=True)
    bot.setup(app, svc, s)
    await app.start()
    loop = asyncio.get_running_loop()

    def decided(night_id: int) -> None:   # called from an HTTP thread when the Mini App locks a night
        fut = asyncio.run_coroutine_threadsafe(bot.announce(app, night_id), loop)
        fut.add_done_callback(lambda f: f.exception() and log.error("announce failed: %s", f.exception()))

    httpd.app.hooks["decided"] = decided
    task = asyncio.create_task(bot.airing_loop(app))
    me = await app.get_me()
    log.info("Bot @%s is live.", me.username)
    await idle()
    task.cancel()
    await app.stop()
    httpd.shutdown()


if __name__ == "__main__":
    asyncio.run(amain())
