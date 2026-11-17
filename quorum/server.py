"""Zero-dependency HTTP server: serves the Mini App and its JSON API."""
from __future__ import annotations

import json
import logging
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import card
from .anilist import AniListError
from .auth import AuthError, validate_init_data
from .config import Settings
from .service import Quorum, QuorumError

log = logging.getLogger("quorum.http")
WEBAPP = Path(__file__).resolve().parent.parent / "webapp"
MIME = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png"}
MAX_BODY = 64 * 1024


def _clean(obj):
    """Drop private keys (leading underscore) before JSON-encoding a service result."""
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items() if not str(k).startswith("_")}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    return obj


class App:
    def __init__(self, settings: Settings, svc: Quorum):
        self.settings, self.svc = settings, svc
        self.hooks: dict = {}   # e.g. hooks["decided"](night_id) set by the bot


def make_handler(app: App):
    class H(BaseHTTPRequestHandler):
        server_version = "Quorum/1.0"

        def log_message(self, fmt, *args):  # route access logs through logging
            log.debug("%s - %s", self.address_string(), fmt % args)

        # -- plumbing ------------------------------------------------------
        def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store" if ctype.startswith("application/json") else "no-cache")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj):
            self._send(code, json.dumps(_clean(obj), ensure_ascii=False).encode(), "application/json; charset=utf-8")

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                raise QuorumError("Request too large.")
            if not n:
                return {}
            try:
                data = json.loads(self.rfile.read(n))
            except ValueError:
                raise QuorumError("Invalid JSON.")
            if not isinstance(data, dict):
                raise QuorumError("Invalid JSON.")
            return data

        def _auth(self) -> dict:
            s = app.settings
            if s.dev_auth and self.headers.get("X-Dev-User"):
                uid, _, name = self.headers["X-Dev-User"].partition(":")
                return {"id": int(uid), "name": name or f"user{uid}", "start_param": self.headers.get("X-Dev-Start", "")}
            return validate_init_data(self.headers.get("X-Init-Data", ""), s.bot_token)

        # -- routing -------------------------------------------------------
        def do_GET(self):
            self._route("GET")

        def do_POST(self):
            self._route("POST")

        def _route(self, method: str):
            path = self.path.split("?", 1)[0]
            try:
                if path == "/health":
                    return self._json(200, {"ok": True})
                if method == "GET" and not path.startswith("/api/"):
                    return self._static(path)
                user = self._auth()
                app.svc.ensure_user(user["id"], user["name"])
                for rx, meth, fn in ROUTES:
                    m = rx.fullmatch(path)
                    if m and meth == method:
                        return fn(self, user, *[int(g) if g.isdigit() else g for g in m.groups()])
                self._json(404, {"error": "Not found"})
            except AuthError as e:
                self._json(401, {"error": str(e)})
            except QuorumError as e:
                self._json(400, {"error": str(e)})
            except AniListError as e:
                self._json(502, {"error": str(e)})
            except Exception:
                log.exception("unhandled error on %s %s", method, path)
                self._json(500, {"error": "Something broke on our side."})

        def _static(self, path: str):
            name = "index.html" if path in ("/", "") else path.lstrip("/")
            f = (WEBAPP / name).resolve()
            if f.parent != WEBAPP.resolve() or not f.is_file():
                return self._json(404, {"error": "Not found"})
            self._send(200, f.read_bytes(), MIME.get(f.suffix, "application/octet-stream"))

    return H


# -- API handlers -----------------------------------------------------------
def _me(h, user):
    svc = h.server.app.svc
    u = svc.user(user["id"]) or {}
    out = {"user": {"id": user["id"], "name": user["name"], "anilist": u.get("anilist")},
           "start_param": user.get("start_param", ""), "dna": None}
    if u.get("anilist"):
        try:
            out["dna"] = svc.dna(user["id"])
        except QuorumError:
            pass
    h._json(200, out)


def _link(h, user):
    svc = h.server.app.svc
    n = svc.link(user["id"], user["name"], str(h._body().get("anilist", "")))
    h._json(200, {"entries": n, "dna": svc.dna(user["id"])})


def _card(h, user):
    svc = h.server.app.svc
    u = svc.user(user["id"]) or {}
    png = card.dna_card(user["name"], u.get("anilist"), svc.dna(user["id"]))
    h._send(200, png, "image/png")


def _night(h, user, nid):
    svc = h.server.app.svc
    n = svc.night(nid)
    if n["status"] == "open":
        svc.join_night(nid, user["id"], user["name"])
    res = svc.result(nid, k=5) if n["status"] != "open" else None
    h._json(200, {"night": svc._ser_night(svc.night(nid)), "members": svc.members(nid),
                  "deck": svc.deck(nid, user["id"]) if n["status"] == "open" else [],
                  "result": res})


def _swipe(h, user, nid):
    b = h._body()
    svc = h.server.app.svc
    svc.swipe(nid, user["id"], user["name"], int(b.get("media_id", 0)), str(b.get("vote", "")))
    h._json(200, {"ok": True})


def _result(h, user, nid):
    h._json(200, h.server.app.svc.result(nid, k=8))


def _decide(h, user, nid):
    app = h.server.app
    n = app.svc.night(nid)
    if n["creator"] != user["id"] and user["id"] not in app.settings.owner_ids:
        raise QuorumError("Only the person who started the night can lock it.")
    res = app.svc.decide(nid)
    hook = app.hooks.get("decided")
    if hook:
        threading.Thread(target=hook, args=(nid,), daemon=True).start()
    h._json(200, res)


def _compat(h, user, other):
    h._json(200, h.server.app.svc.compat(user["id"], other))


ROUTES = [
    (re.compile(r"/api/me"), "GET", _me),
    (re.compile(r"/api/link"), "POST", _link),
    (re.compile(r"/api/me/card\.png"), "GET", _card),
    (re.compile(r"/api/night/(\d+)"), "GET", _night),
    (re.compile(r"/api/night/(\d+)/swipe"), "POST", _swipe),
    (re.compile(r"/api/night/(\d+)/result"), "GET", _result),
    (re.compile(r"/api/night/(\d+)/decide"), "POST", _decide),
    (re.compile(r"/api/compat/(\d+)"), "GET", _compat),
]


def serve(settings: Settings, svc: Quorum, hooks: dict | None = None, port: int | None = None):
    app = App(settings, svc)
    if hooks:
        app.hooks.update(hooks)
    httpd = ThreadingHTTPServer(("0.0.0.0", settings.port if port is None else port), make_handler(app))
    httpd.app = app
    httpd.daemon_threads = True
    return httpd
