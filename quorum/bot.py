"""Telegram front-end (Kurigram / Pyrogram). Thin: all logic lives in quorum.service."""
from __future__ import annotations

import asyncio
import html
import logging

from pyrogram import enums, filters
from pyrogram.handlers import CallbackQueryHandler, MessageHandler
from pyrogram.types import InlineKeyboardButton as Btn
from pyrogram.types import InlineKeyboardMarkup as Kb
from pyrogram.types import WebAppInfo

from . import card, consensus
from .anilist import AniListError
from .service import Quorum, QuorumError

log = logging.getLogger("quorum.bot")
HTML = enums.ParseMode.HTML
esc = html.escape

CTX: dict = {}   # filled by setup(): svc, settings


def svc() -> Quorum:
    return CTX["svc"]


async def run(fn, *a):
    return await asyncio.to_thread(fn, *a)


def uname(u) -> str:
    return (u.first_name or u.username or str(u.id))[:24]


def args_of(message) -> str:
    parts = (message.text or message.caption or "").split(None, 1)
    return parts[1].strip() if len(parts) > 1 else ""


async def safe(message, coro):
    """Run a coroutine, turning expected errors into friendly replies."""
    try:
        return await coro
    except (QuorumError, AniListError) as e:
        await message.reply_text(f"⚠️ {esc(str(e))}", parse_mode=HTML)
    except Exception:
        log.exception("handler failed")
        await message.reply_text("💥 Something broke on my side. Try again in a moment.")


# -------------------------------------------------------------------- links
async def miniapp_link(client, night_id: int | None = None) -> str:
    s = CTX["settings"]
    start = f"night_{night_id}" if night_id else ""
    if s.miniapp_link:
        return s.miniapp_link + (f"?startapp={start}" if start else "")
    if "username" not in CTX:
        CTX["username"] = (await client.get_me()).username
    return f"https://t.me/{CTX['username']}" + (f"?startapp={start}" if start else "")


# -------------------------------------------------------------------- basics
HELP = (
    "<b>Quorum</b> - fair anime nights, taste DNA and spoiler-proof chat.\n\n"
    "<b>Setup</b>\n/link <code>anilist_name</code> - connect your public AniList\n"
    "/dna - your Taste DNA card\n/forget - delete everything I stored about you\n/compat - reply to someone: how compatible are you?\n\n"
    "<b>Group nights</b>\n/night <code>[cozy|hype|mindbender|cry|spooky] [max=13] [rewatch]</code>\n"
    "Everyone swipes in the Mini App (or taps Quick vote); the creator locks the pick.\n\n"
    "<b>Spoiler Shield</b>\n/spoiler <code>Title | ep | text</code> or <code>ep text</code> for the group's current show\n"
    "/progress <code>[Title |] ep</code> - tell me how far you are\n"
    "/watching <code>Title</code> - set the group's show + get episode alerts"
)


async def cmd_start(client, message):
    s = CTX["settings"]
    payload = message.command[1] if len(message.command) > 1 else ""
    url = s.public_url + ("/?night=" + payload[6:] if payload.startswith("night_") else "")
    rows = []
    if message.chat.type == enums.ChatType.PRIVATE:
        rows.append([Btn("🎬 Open Quorum", web_app=WebAppInfo(url=url))])
    await message.reply_text(HELP, parse_mode=HTML, reply_markup=Kb(rows) if rows else None)


async def cmd_help(client, message):
    await message.reply_text(HELP, parse_mode=HTML)


async def cmd_link(client, message):
    name = args_of(message)
    if not name:
        return await message.reply_text("Usage: /link <code>your_anilist_username</code>", parse_mode=HTML)

    async def go():
        n = await run(svc().link, message.from_user.id, uname(message.from_user), name)
        dna = await run(svc().dna, message.from_user.id)
        await message.reply_text(
            f"✅ Linked <b>{esc(name)}</b> ({n} titles).\nYou are <b>{esc(dna['archetype'])}</b>.\n"
            "Try /dna for your card.", parse_mode=HTML)
    await safe(message, go())


async def cmd_forget(client, message):
    await run(svc().forget, message.from_user.id)
    await message.reply_text("🧹 Done. Your AniList data, swipes, progress and history are deleted.")


async def cmd_dna(client, message):
    async def go():
        uid = message.from_user.id
        dna = await run(svc().dna, uid)
        u = await run(svc().user, uid)
        png = await run(card.dna_card, uname(message.from_user), (u or {}).get("anilist"), dna)
        import io
        bio = io.BytesIO(png)
        bio.name = "dna.png"
        await message.reply_photo(bio, caption=f"🧬 <b>{esc(dna['archetype'])}</b>\n{esc(dna['blurb'])}", parse_mode=HTML)
    await safe(message, go())


async def cmd_compat(client, message):
    other = message.reply_to_message.from_user if message.reply_to_message else None
    if not other or other.is_bot or other.id == message.from_user.id:
        return await message.reply_text("Reply to someone else's message with /compat.")

    async def go():
        c = await run(svc().compat, message.from_user.id, other.id)
        lines = [f"💞 <b>{esc(uname(message.from_user))} × {esc(uname(other))}</b>: <b>{c['percent']}%</b>"]
        if c["common_ground"]:
            lines.append("Common ground: " + ", ".join(esc(x) for x in c["common_ground"]))
        if c["friction"]:
            lines.append("Friction: " + ", ".join(esc(x) for x in c["friction"]))
        if c["shared_favorites"]:
            lines.append("Both adore: " + ", ".join(esc(x) for x in c["shared_favorites"][:3]))
        if c["bridge_picks"]:
            lines.append("\n🌉 <b>Bridge picks</b> (you'd both enjoy):")
            lines += [f"• {esc(p['title'])} - {min(m['score'] for m in p['per_member'])}+" for p in c["bridge_picks"]]
        await message.reply_text("\n".join(lines), parse_mode=HTML)
    await safe(message, go())


# -------------------------------------------------------------------- nights
def parse_night_args(text: str) -> dict:
    out = {"mood": None, "max_eps": None, "rewatch": False, "adult": False}
    for tok in text.lower().split():
        if tok in consensus.MOODS:
            out["mood"] = tok
        elif tok.startswith("max="):
            try:
                out["max_eps"] = max(1, min(2000, int(tok[4:])))
            except ValueError:
                raise QuorumError("max= needs a number, e.g. max=13")
        elif tok == "rewatch":
            out["rewatch"] = True
        elif tok == "adult":
            out["adult"] = True
        else:
            raise QuorumError(f"Don't know '{tok}'. Moods: {', '.join(consensus.MOODS)}; options: max=N rewatch adult")
    return out


def night_text(nid: int) -> str:
    q = svc()
    n, mem = q.night(nid), q.members(nid)
    mood = consensus.MOODS.get(n["mood"] or "")
    rules = [x for x in (f"≤{n['max_eps']} eps" if n["max_eps"] else "", "rewatch ok" if n["rewatch"] else "",
                         "18+ allowed" if n["adult"] else "") if x]
    who = ", ".join(f"{esc(m['name'])}{' ✓' if m['linked'] else ' (guest)'}" for m in mem)
    return (f"🎬 <b>Movie Night #{nid}</b>" + (f"  {mood['emoji']} {mood['label']}" if mood else "") + "\n"
            + (f"Rules: {' · '.join(rules)}\n" if rules else "")
            + f"\n<b>In ({len(mem)}):</b> {who}\n<i>✓ = AniList linked, so I know your taste. Guests still count via swipes.</i>\n\n"
            "Swipe in the Mini App or use Quick vote. When everyone's in, the creator hits Lock.")


async def night_kb(client, nid: int):
    link = await miniapp_link(client, nid)
    return Kb([[Btn("🎬 Swipe (Mini App)", url=link)],
               [Btn("🙋 Join", callback_data=f"nt:j:{nid}"), Btn("🗳 Quick vote", callback_data=f"nt:q:{nid}")],
               [Btn("⚡ Lock & decide", callback_data=f"nt:d:{nid}")]])


async def cmd_night(client, message):
    async def go():
        opts = parse_night_args(args_of(message))
        u = message.from_user
        nid = await run(lambda: svc().create_night(message.chat.id, u.id, uname(u), **opts))
        sent = await message.reply_text(await run(night_text, nid), parse_mode=HTML,
                                        reply_markup=await night_kb(client, nid))
        await run(svc().set_night_message, nid, sent.id)
    await safe(message, go())


async def refresh_night(client, query, nid: int):
    await query.message.edit_text(await run(night_text, nid), parse_mode=HTML, reply_markup=await night_kb(client, nid))


async def is_admin(client, chat_id: int, user_id: int) -> bool:
    if user_id in CTX["settings"].owner_ids:
        return True
    try:
        m = await client.get_chat_member(chat_id, user_id)
        return m.status in (enums.ChatMemberStatus.OWNER, enums.ChatMemberStatus.ADMINISTRATOR)
    except Exception:
        return False


def verdict(nid: int) -> tuple[dict, list[dict], dict, str]:
    """-> (winner item, runner-ups, night, caption)"""
    q = svc()
    res = q.result(nid, k=40)
    n = res["night"]
    items = res["ranking"]
    win = next((i for i in items if i["id"] == n["winner"]), None)
    if win is None:
        raise QuorumError("Couldn't rebuild the verdict.")
    runners = [i for i in items if i["id"] != win["id"]][:3]
    mins = ", ".join(f"{esc(p['name'])} {p['score']}" for p in win["per_member"])
    lines = [f"🏆 <b>{esc(win['title'])}</b>" + (f"  <i>({esc(win['badge'])})</i>" if win.get("badge") else ""),
             f"Predicted enjoyment: {mins}"]
    if win.get("runtime"):
        h, m = divmod(win["runtime"], 60)
        lines.append(f"⏱ {win['episodes']} eps · {h}h{m:02d}m" + (" · airing weekly" if win["airing"] else ""))
    if win.get("sacrifice"):
        lines.append(f"🤝 {esc(win['sacrifice'])} takes one for the team - their next vote counts extra.")
    if n.get("fairness") is not None:
        lines.append(f"⚖️ Fairness {n['fairness']}%")
    if runners:
        lines.append("\nRunners-up: " + " · ".join(esc(r["title"]) for r in runners))
    lines.append("\nUse /spoiler here - it stays locked until people catch up. 🛡")
    return win, runners, n, "\n".join(lines)


async def announce(client, nid: int):
    """Post the verdict card to the group (also called when the Mini App locks a night)."""
    import io
    win, _, n, caption = await run(verdict, nid)
    cover = await run(card.fetch_image, win.get("cover"))
    png = await run(card.verdict_card, win, n.get("fairness"), n.get("mood_label"), cover)
    bio = io.BytesIO(png)
    bio.name = "verdict.png"
    await client.send_photo(n["chat_id"], bio, caption=caption, parse_mode=HTML)
    night = await run(svc().night, nid)
    if night.get("msg_id"):
        try:
            await client.edit_message_text(n["chat_id"], night["msg_id"], f"🎬 Movie Night #{nid} - <b>decided</b> ✅", parse_mode=HTML)
        except Exception:
            pass


async def cb_night(client, query):
    _, act, nid, *rest = query.data.split(":")
    nid = int(nid)
    u = query.from_user
    q = svc()
    try:
        if act == "j":
            joined = await run(q.join_night, nid, u.id, uname(u))
            await query.answer("You're in!" if joined else "Already in.")
            if joined:
                await refresh_night(client, query, nid)
        elif act == "q":
            await run(q.join_night, nid, u.id, uname(u))
            res = await run(q.result, nid, 8)
            rows = [[Btn(f"{'👍 ' if i['likes'] else ''}{i['likes'] or ''} {i['title'][:30]}".strip(),
                         callback_data=f"nt:v:{nid}:{i['id']}")] for i in res["ranking"]]
            rows.append([Btn("⬅️ Back", callback_data=f"nt:b:{nid}")])
            await query.message.edit_text("🗳 <b>Quick vote</b> - tap to like / unlike. Ranking re-sorts as people vote.",
                                          parse_mode=HTML, reply_markup=Kb(rows))
            await query.answer()
        elif act == "v":
            liked = await run(q.toggle_like, nid, u.id, uname(u), int(rest[0]))
            await query.answer("Liked 👍" if liked else "Removed")
            res = await run(q.result, nid, 8)
            rows = [[Btn(f"{'👍 ' + str(i['likes']) + ' ' if i['likes'] else ''}{i['title'][:30]}",
                         callback_data=f"nt:v:{nid}:{i['id']}")] for i in res["ranking"]]
            rows.append([Btn("⬅️ Back", callback_data=f"nt:b:{nid}")])
            await query.message.edit_reply_markup(Kb(rows))
        elif act == "b":
            await refresh_night(client, query, nid)
            await query.answer()
        elif act == "d":
            n = await run(q.night, nid)
            if u.id != n["creator"] and not await is_admin(client, query.message.chat.id, u.id):
                return await query.answer("Only the creator or an admin can lock the night.", show_alert=True)
            await run(q.decide, nid)
            await query.answer("Locked!")
            await announce(client, nid)
    except QuorumError as e:
        await query.answer(str(e)[:190], show_alert=True)
    except Exception:
        log.exception("night callback failed")
        await query.answer("Something broke. Try again.", show_alert=True)


# -------------------------------------------------------------------- spoilers / progress
async def resolve_media(chat_id: int, title: str):
    found = await run(svc().find_media, title)
    if not found:
        raise QuorumError(f"Couldn't find an anime called “{title}”.")
    return found[0]


async def parse_title_ep(message, rest: str, need_text: bool):
    """Accept 'Title | ep [| text]' or 'ep [text]' (current show). -> (media, ep, text)"""
    if "|" in rest:
        parts = [p.strip() for p in rest.split("|", 2)]
        if len(parts) < 2 or not parts[1].isdigit() or (need_text and (len(parts) < 3 or not parts[2])):
            raise QuorumError("Format: Title | episode | text")
        return await resolve_media(message.chat.id, parts[0]), int(parts[1]), parts[2] if len(parts) > 2 else ""
    bits = rest.split(None, 1)
    if not bits or not bits[0].isdigit():
        raise QuorumError("Format: <episode> <text>  (or Title | episode | text)")
    media = await run(svc().current_show, message.chat.id)
    if not media:
        raise QuorumError("No current show for this chat. Use /watching <title> or the Title | ep | text form.")
    text = bits[1] if len(bits) > 1 else ""
    if need_text and not text:
        raise QuorumError("Add the spoiler text after the episode number.")
    return media, int(bits[0]), text


async def cmd_spoiler(client, message):
    async def go():
        media, ep, text = await parse_title_ep(message, args_of(message), need_text=True)
        u = message.from_user
        sid = await run(svc().add_spoiler, message.chat.id, media.id, ep, u.id, uname(u), text)
        try:
            await message.delete()   # needs the delete-messages admin right; otherwise the raw text stays visible
        except Exception:
            await message.reply_text("ℹ️ Give me the “Delete messages” admin right and I'll remove your original too.")
        await client.send_message(
            message.chat.id,
            f"🛡 <b>Spoiler Shield</b>\n<b>{esc(media.title)}</b> · episode {ep}\nfrom {esc(uname(u))}",
            parse_mode=HTML,
            reply_markup=Kb([[Btn("👁 Reveal (if you're caught up)", callback_data=f"sp:r:{sid}")],
                             [Btn("☠️ Reveal anyway", callback_data=f"sp:f:{sid}")]]))
    await safe(message, go())


async def cb_spoiler(client, query):
    _, act, sid = query.data.split(":")
    verdict_, text = await run(svc().reveal, int(sid), query.from_user.id, act == "f")
    prefix = {"ok": "👁 ", "forced": "☠️ "}.get(verdict_, "")
    await query.answer(prefix + text, show_alert=True)


async def cmd_progress(client, message):
    async def go():
        rest = args_of(message)
        u = message.from_user
        if not rest:
            media = await run(svc().current_show, message.chat.id)
            if not media:
                raise QuorumError("Usage: /progress Title | ep   (or /progress ep for the current show)")
            p = await run(svc().progress_for, u.id, media.id)
            return await message.reply_text(f"You're at episode {p if p is not None and p < 99999 else '?'} of {esc(media.title)}.",
                                            parse_mode=HTML)
        media, ep, _ = await parse_title_ep(message, rest, need_text=False)
        await run(svc().set_progress, u.id, media.id, ep)
        await message.reply_text(f"📍 Saved: <b>{esc(media.title)}</b> episode {ep}. Spoilers up to there unlock for you.",
                                 parse_mode=HTML)
    await safe(message, go())


async def cmd_watching(client, message):
    async def go():
        title = args_of(message)
        if not title:
            m = await run(svc().current_show, message.chat.id)
            return await message.reply_text(f"Currently watching: <b>{esc(m.title)}</b>" if m else "Nothing set. /watching Title",
                                            parse_mode=HTML)
        media = await resolve_media(message.chat.id, title)
        await run(svc().set_show, message.chat.id, media)
        extra = " I'll announce new episodes here." if media.status == "RELEASING" else ""
        await message.reply_text(f"📺 Now watching <b>{esc(media.title)}</b>.{extra}", parse_mode=HTML)
    await safe(message, go())


async def airing_loop(client, every: int = 600):
    while True:
        try:
            for n in await run(svc().due_notifications):
                m = n["media"]
                await client.send_message(
                    n["chat_id"], f"📺 <b>{esc(m.title)}</b> episode <b>{n['episode']}</b> just aired!\n"
                    "Spoilers? Use /spoiler so nobody gets hurt. 🛡", parse_mode=HTML)
        except Exception:
            log.exception("airing loop")
        await asyncio.sleep(every)


# -------------------------------------------------------------------- wiring
def setup(app, service: Quorum, settings) -> None:
    CTX.update(svc=service, settings=settings)
    cmds = {"start": cmd_start, "help": cmd_help, "link": cmd_link, "dna": cmd_dna, "compat": cmd_compat,
            "night": cmd_night, "forget": cmd_forget, "spoiler": cmd_spoiler, "progress": cmd_progress, "watching": cmd_watching}
    for name, fn in cmds.items():
        app.add_handler(MessageHandler(fn, filters.command(name)))
    app.add_handler(CallbackQueryHandler(cb_night, filters.regex(r"^nt:")))
    app.add_handler(CallbackQueryHandler(cb_spoiler, filters.regex(r"^sp:")))
