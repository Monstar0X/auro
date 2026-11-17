from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    """Tiny .env reader so the core has zero third-party dependencies."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _flag(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    bot_token: str
    api_id: int
    api_hash: str
    public_url: str          # https URL where the Mini App is served
    miniapp_link: str        # t.me/<bot>/<app> direct link (works inside groups)
    port: int
    db_path: str
    demo: bool               # use built-in fixtures instead of the AniList API
    dev_auth: bool           # accept X-Dev-User header (local testing ONLY)
    anilist_url: str
    list_ttl_hours: int
    owner_ids: frozenset[int]


def load() -> Settings:
    _load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    owners = {int(x) for x in os.getenv("OWNER_IDS", "").replace(" ", "").split(",") if x.isdigit()}
    return Settings(
        bot_token=os.getenv("BOT_TOKEN", ""),
        api_id=int(os.getenv("API_ID", "0") or 0),
        api_hash=os.getenv("API_HASH", ""),
        public_url=os.getenv("PUBLIC_URL", "http://localhost:8080").rstrip("/"),
        miniapp_link=os.getenv("MINIAPP_LINK", "").rstrip("/"),
        port=int(os.getenv("PORT", "8080")),
        db_path=os.getenv("DB_PATH", "data/quorum.db"),
        demo=_flag("QUORUM_DEMO"),
        dev_auth=_flag("DEV_AUTH"),
        anilist_url=os.getenv("ANILIST_URL", "https://graphql.anilist.co"),
        list_ttl_hours=int(os.getenv("LIST_TTL_HOURS", "12")),
        owner_ids=frozenset(owners),
    )
