"""Shareable PNG cards (Pillow only): Taste DNA and the Night verdict."""
from __future__ import annotations

import io
import math
import urllib.request

from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 675
BG1, BG2 = (14, 16, 30), (38, 22, 64)
ACCENT, ACCENT2, INK, MUTED = (255, 107, 157), (110, 231, 255), (244, 244, 252), (150, 154, 184)

_FONT_DIRS = ["/usr/share/fonts/truetype/dejavu/", "/usr/share/fonts/dejavu/", "/Library/Fonts/",
              "C:/Windows/Fonts/", "/usr/share/fonts/truetype/liberation/"]


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    names = (["DejaVuSans-Bold.ttf", "Arial Bold.ttf", "arialbd.ttf", "LiberationSans-Bold.ttf"] if bold
             else ["DejaVuSans.ttf", "Arial.ttf", "arial.ttf", "LiberationSans-Regular.ttf"])
    for d in _FONT_DIRS:
        for n in names:
            try:
                return ImageFont.truetype(d + n, size)
            except OSError:
                continue
    return ImageFont.load_default(size)


def _gradient() -> Image.Image:
    img = Image.new("RGB", (W, H), BG1)
    px = img.load()
    for y in range(H):
        for x in range(0, W):
            t = (x / W * 0.6 + y / H * 0.4)
            px[x, y] = tuple(int(BG1[i] + (BG2[i] - BG1[i]) * t) for i in range(3))
    return img


def _wrap(draw: ImageDraw.ImageDraw, text: str, fnt, width: int) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if draw.textlength(trial, font=fnt) <= width:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def _radar(draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int, labels: list[str], values: list[float]) -> None:
    n = len(labels)
    if n < 3:
        return
    ang = [-math.pi / 2 + 2 * math.pi * i / n for i in range(n)]
    for ring in (0.25, 0.5, 0.75, 1.0):
        pts = [(cx + r * ring * math.cos(a), cy + r * ring * math.sin(a)) for a in ang]
        draw.polygon(pts, outline=(70, 74, 110))
    for a in ang:
        draw.line([(cx, cy), (cx + r * math.cos(a), cy + r * math.sin(a))], fill=(70, 74, 110))
    pts = [(cx + r * max(0.08, v) * math.cos(a), cy + r * max(0.08, v) * math.sin(a)) for a, v in zip(ang, values)]
    draw.polygon(pts, fill=(255, 107, 157, 90), outline=ACCENT)
    for (x, y) in pts:
        draw.ellipse([x - 5, y - 5, x + 5, y + 5], fill=ACCENT2)
    f = font(22, True)
    for a, lab in zip(ang, labels):
        x, y = cx + (r + 34) * math.cos(a), cy + (r + 30) * math.sin(a)
        w = draw.textlength(lab, font=f)
        draw.text((x - w / 2, y - 12), lab, font=f, fill=INK)


def dna_card(name: str, anilist: str | None, dna: dict) -> bytes:
    img = _gradient().convert("RGBA")
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    d.text((60, 44), "QUORUM  •  TASTE DNA", font=font(22, True), fill=ACCENT2)
    d.text((60, 92), dna["archetype"], font=font(58, True), fill=INK)
    y = 176
    for line in _wrap(d, dna["blurb"], font(25), 560)[:3]:
        d.text((60, y), line, font=font(25), fill=MUTED)
        y += 36
    stats = [("AVG SCORE", f'{dna["mean_score"]:.0f}'), ("JUDGE", dna["judge"]),
             ("EXPLORER", f'{dna["explorer"]}%'),
             ("VS CROWD", f'{dna["crowd_delta"]:+.0f}')]
    y = 330
    for i, (k, v) in enumerate(stats):
        x = 60 + (i % 2) * 290
        yy = y + (i // 2) * 105
        d.rounded_rectangle([x, yy, x + 270, yy + 90], 16, fill=(255, 255, 255, 22))
        d.text((x + 18, yy + 12), k, font=font(17, True), fill=MUTED)
        d.text((x + 18, yy + 38), v, font=font(34, True), fill=INK)
    tags = ", ".join(t["name"] for t in dna["tags"][:3])
    if tags:
        d.text((60, 560), "Obsessed with: " + tags, font=font(23), fill=INK)
    who = name + (f"  (anilist.co/user/{anilist})" if anilist else "")
    d.text((60, 618), who, font=font(21), fill=MUTED)
    g = dna["genres"][:6]
    if len(g) >= 3:
        mx = max(x["weight"] for x in g)
        vals = [max(0.0, (x["weight"] + 0.15) / (mx + 0.15)) for x in g]
        _radar(d, 900, 345, 170, [x["name"] for x in g], vals)
    img.alpha_composite(ov)
    out = io.BytesIO()
    img.convert("RGB").save(out, "PNG")
    return out.getvalue()


def fetch_image(url: str | None, timeout: int = 8) -> Image.Image | None:
    if not url:
        return None
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Quorum/1.0"}), timeout=timeout) as r:
            return Image.open(io.BytesIO(r.read())).convert("RGB")
    except Exception:
        return None


def verdict_card(item: dict, fairness: int | None, mood_label: str | None, cover: Image.Image | None = None) -> bytes:
    """item: a serialised ranking entry from Quorum._ser_item."""
    img = _gradient().convert("RGBA")
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    px, pw, ph = 60, 380, 540
    if cover:
        c = cover.copy()
        c.thumbnail((pw * 2, ph * 2))
        c = c.resize((pw, int(c.height * pw / c.width)))
        c = c.crop((0, 0, pw, min(ph, c.height)))
        img.paste(c, (px, 68))
    else:
        d.rounded_rectangle([px, 68, px + pw, 68 + ph], 24, fill=(255, 255, 255, 25))
        d.text((px + 40, 300), item["title"][:1], font=font(160, True), fill=(255, 255, 255, 60))
    x = 480
    d.text((x, 60), "TONIGHT'S VERDICT" + (f"  •  {mood_label.split(' ', 1)[-1].upper()}" if mood_label else ""),
           font=font(22, True), fill=ACCENT2)
    y = 104
    for line in _wrap(d, item["title"], font(52, True), 660)[:3]:
        d.text((x, y), line, font=font(52, True), fill=INK)
        y += 64
    meta = []
    if item.get("episodes"):
        meta.append(f'{item["episodes"]} eps')
    if item.get("runtime"):
        h, m = divmod(item["runtime"], 60)
        meta.append(f"{h}h {m:02d}m total")
    if item.get("genres"):
        meta.append(" / ".join(item["genres"][:3]))
    d.text((x, y + 6), "  •  ".join(meta), font=font(23), fill=MUTED)
    y += 70
    d.text((x, y), "WHY IT WON", font=font(18, True), fill=ACCENT)
    y += 30
    for pm in item["per_member"][:6]:
        d.text((x, y), pm["name"][:16], font=font(22), fill=INK)
        d.rounded_rectangle([x + 190, y + 6, x + 190 + 380, y + 24], 9, fill=(255, 255, 255, 28))
        w = int(380 * max(0, min(100, pm["score"])) / 100)
        d.rounded_rectangle([x + 190, y + 6, x + 190 + w, y + 24], 9, fill=ACCENT if pm["score"] < 70 else ACCENT2)
        d.text((x + 585, y), str(pm["score"]), font=font(22, True), fill=INK)
        y += 36
    y = max(y + 14, 520)
    badge = item.get("badge") or ""
    d.rounded_rectangle([x, y, x + 250, y + 52], 26, fill=(255, 107, 157, 70), outline=ACCENT)
    d.text((x + 24, y + 12), badge, font=font(23, True), fill=INK)
    if fairness is not None:
        d.text((x + 280, y + 12), f"Fairness {fairness}%", font=font(23, True), fill=INK)
    d.text((x, 620), "Quorum  •  every vote counted, nobody steamrolled", font=font(18), fill=MUTED)
    img.alpha_composite(ov)
    out = io.BytesIO()
    img.convert("RGB").save(out, "PNG")
    return out.getvalue()
