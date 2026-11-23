"""Draws the overlay as a transparent RGBA image (Pillow).

Rendering to an image gives true per-pixel transparency: a faint, glassy
backdrop with fully crisp text on top, plus soft shadows for legibility.
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .config import FONTS
from .sheet import distribute

# Palette (RGBA) ---------------------------------------------------------------
GOLD = (240, 192, 79, 255)
GOLD_SOFT = (240, 192, 79, 210)
TEXT = (238, 241, 246, 255)
DIM = (150, 158, 171, 255)
HEAD = (214, 219, 227, 255)
DANGER = (239, 123, 108, 255)
PANEL = (8, 11, 16)
EDGE = (255, 255, 255, 26)
KEYCAP = (255, 255, 255, 18)
KEYCAP_EDGE = (255, 255, 255, 34)

_FONT_FILES = {
    "ui": ["Inter-Medium.otf", "segoeui.ttf", "DejaVuSans.ttf"],
    "ui_regular": ["Inter-Regular.otf", "segoeui.ttf", "DejaVuSans.ttf"],
    "mono": ["JetBrainsMono-Medium.ttf", "consola.ttf", "DejaVuSansMono.ttf"],
    "mono_bold": ["JetBrainsMono-Bold.ttf", "consolab.ttf", "DejaVuSansMono-Bold.ttf"],
}
_cache = {}


def _font(kind: str, px: int) -> ImageFont.FreeTypeFont:
    key = (kind, px)
    if key in _cache:
        return _cache[key]
    for name in _FONT_FILES[kind]:
        for folder in (FONTS, os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts"),
                       "/usr/share/fonts/truetype/dejavu"):
            path = os.path.join(folder, name)
            if os.path.exists(path):
                try:
                    f = ImageFont.truetype(path, px)
                    _cache[key] = f
                    return f
                except OSError:
                    pass
    f = ImageFont.load_default(px)
    _cache[key] = f
    return f


class _Canvas:
    """Collects drawing ops on separate layers (backdrop / text) at scale."""

    def __init__(self, u: float):
        self.u = u
        self.ops = []  # (kind, args)

    def text(self, x, y, s, font, fill, tracking=0.0):
        self.ops.append(("text", (x, y, s, font, fill, tracking)))

    def cap(self, x1, y1, x2, y2, r):
        self.ops.append(("cap", (x1, y1, x2, y2, r)))


def _measure(font, s: str, tracking: float = 0.0) -> float:
    if not s:
        return 0.0
    if not tracking:
        return font.getlength(s)
    return sum(font.getlength(ch) for ch in s) + tracking * (len(s) - 1)


def _draw_text(d: ImageDraw.ImageDraw, x, y, s, font, fill, tracking=0.0):
    if not tracking:
        d.text((x, y), s, font=font, fill=fill)
        return
    for ch in s:
        d.text((x, y), ch, font=font, fill=fill)
        x += font.getlength(ch) + tracking


def render_overlay(title: str, pages: list, page_idx: int, settings: dict,
                   scale: float = 1.0, hint: str = "", warning: str = "") -> Image.Image:
    """Return the overlay as an RGBA image, ready to be shown or previewed."""
    fs = int(settings.get("font_size", 11))
    base = fs * 1.36 * scale                      # point size -> pixels
    u = base / 15.0                               # layout unit
    backdrop = float(settings.get("backdrop", 0.55))

    f_act = _font("ui", round(base * 0.93))
    f_key = _font("mono_bold", round(base * 0.80))
    f_hdr = _font("mono_bold", round(base * 0.70))
    f_sec = _font("mono_bold", round(base * 0.64))
    f_col = _font("mono", round(base * 0.62))
    f_note = _font("ui_regular", round(base * 0.80))
    trk_hdr, trk_sec = base * 0.10, base * 0.12

    def tall(font):
        a, d = font.getmetrics()
        return a + d

    pad_x, pad_y = 16 * u, 13 * u
    cap_px, cap_py = 6 * u, 2.2 * u
    cap_h = tall(f_key) * 0.86 + 2 * cap_py
    row_h = max(cap_h, tall(f_act)) + 5 * u
    gap_key, gap_cell, gap_col, gap_sec = 10 * u, 16 * u, 28 * u, 12 * u

    cv = _Canvas(u)

    # ---- header ----------------------------------------------------------
    y = pad_y
    x = pad_x
    hdr_mid = y + tall(f_hdr) / 2
    dot = 5 * u
    cv.ops.append(("rect", (x, hdr_mid - dot / 2 - u * 0.6, x + dot, hdr_mid + dot / 2 - u * 0.6, GOLD)))
    x += dot + 9 * u
    head = (title or "CHEAT SHEET").upper()
    cv.text(x, y, head, f_hdr, HEAD, trk_hdr)
    head_end = x + _measure(f_hdr, head, trk_hdr)

    right_parts = []
    if pages:
        page_idx %= len(pages)
        page = pages[page_idx]
        if page["title"]:
            right_parts.append((page["title"].upper(), GOLD))
        if len(pages) > 1:
            right_parts.append((f"{page_idx + 1:02d}/{len(pages):02d}", DIM))
    right_w = sum(_measure(f_hdr, s, trk_hdr) for s, _ in right_parts) + \
        (12 * u if len(right_parts) > 1 else 0)

    y += tall(f_hdr) + 9 * u
    divider_y = y
    y += 1 + 11 * u

    # ---- body --------------------------------------------------------------
    body_right = head_end + (24 * u + right_w if right_parts else 0)
    bottom = y
    if not pages:
        msg = "No hotkeys yet. Open Cheat Sheet to add some."
        cv.text(pad_x, y, msg, f_act, DIM)
        body_right = max(body_right, pad_x + _measure(f_act, msg))
        bottom = y + row_h
    else:
        x = pad_x
        for col in distribute(page["sections"], int(settings.get("columns", 3))):
            rows = [r for s in col for r in s["rows"]]
            key_w = max([_measure(f_key, r[1]) + 2 * cap_px for r in rows
                         if r[0] == "row" and r[1]] or [0])
            ncell = max([len(r[2]) for r in rows if r[0] != "note"] or [0])
            cell_w = [0.0] * ncell
            for kind, key, cells in rows:
                if kind == "note":
                    continue
                for i, c in enumerate(cells):
                    w = _measure(f_col, c.upper(), trk_sec * 0.6) if kind == "head" \
                        else _measure(f_act, c)
                    cell_w[i] = max(cell_w[i], w)
            cell_x, cx = [], x + key_w + gap_key
            for w in cell_w:
                cell_x.append(cx)
                cx += w + gap_cell
            col_w = max(cx - gap_cell - x, key_w)

            cy = y
            for si, sec in enumerate(col):
                if si:
                    cy += gap_sec
                if sec["title"]:
                    t = sec["title"].upper()
                    cv.text(x, cy, t, f_sec, GOLD_SOFT, trk_sec)
                    col_w = max(col_w, _measure(f_sec, t, trk_sec))
                    cy += tall(f_sec) + 6 * u
                for kind, key, cells in sec["rows"]:
                    mid = cy + row_h / 2
                    if kind == "note":
                        cv.text(x, mid - tall(f_note) / 2, cells[0], f_note, DIM)
                        col_w = max(col_w, _measure(f_note, cells[0]))
                    elif kind == "head":
                        for i, c in enumerate(cells):
                            cv.text(cell_x[i], mid - tall(f_col) / 2 + u, c.upper(),
                                    f_col, DIM, trk_sec * 0.6)
                    else:
                        if key:
                            kw = _measure(f_key, key) + 2 * cap_px
                            kx2 = x + key_w
                            kx1 = kx2 - kw
                            cv.cap(kx1, mid - cap_h / 2, kx2, mid + cap_h / 2, 4 * u)
                            ka, kd = f_key.getmetrics()
                            cv.text(kx1 + cap_px, mid - (ka + kd) / 2 - u * 0.4, key, f_key, GOLD)
                        for i, c in enumerate(cells):
                            cv.text(cell_x[i], mid - tall(f_act) / 2 - u * 0.4, c, f_act, TEXT)
                    cy += row_h
            bottom = max(bottom, cy)
            body_right = max(body_right, x + col_w)
            x += col_w + gap_col

    for msg, color in ((hint, DIM), (warning, DANGER)):
        if msg:
            bottom += 6 * u
            cv.text(pad_x, bottom, msg, f_note, color)
            body_right = max(body_right, pad_x + _measure(f_note, msg))
            bottom += tall(f_note)

    W = int(body_right + pad_x + 0.5)
    H = int(bottom + pad_y - 3 * u + 0.5)

    # Right-aligned header parts now that the width is known.
    rx = W - pad_x
    for s, color in reversed(right_parts):
        w = _measure(f_hdr, s, trk_hdr)
        rx -= w
        cv.text(rx, pad_y, s, f_hdr, color, trk_hdr)
        rx -= 12 * u

    # ---- compose -----------------------------------------------------------
    m = int(6 * u) + 2                       # margin for the soft shadow
    size = (W + 2 * m, H + 2 * m)
    img = Image.new("RGBA", size, (0, 0, 0, 0))

    # Backdrop: faint glass panel + hairline edge + HUD corner ticks.
    if backdrop > 0:
        glow = Image.new("RGBA", size, (0, 0, 0, 0))
        ImageDraw.Draw(glow).rounded_rectangle(
            (m, m + 2 * u, m + W, m + H + 2 * u), radius=12 * u,
            fill=(0, 0, 0, int(90 * backdrop)))
        img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(6 * u)))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((m, m, m + W - 1, m + H - 1), radius=10 * u,
                            fill=PANEL + (int(255 * backdrop),),
                            outline=EDGE[:3] + (int(EDGE[3] * min(1, backdrop * 1.8)),), width=1)
    d = ImageDraw.Draw(img)
    t = max(1, round(1.4 * u))
    L = 11 * u
    g = GOLD[:3] + (200,)
    # top-left and bottom-right corner ticks
    d.line((m + 1, m + 10 * u, m + 1, m + 1, m + L, m + 1), fill=g, width=t, joint="curve")
    d.line((m + W - 2, m + H - 10 * u, m + W - 2, m + H - 2, m + W - L, m + H - 2), fill=g, width=t, joint="curve")
    # divider with a short gold lead-in
    d.line((m + pad_x, m + divider_y, m + W - pad_x, m + divider_y), fill=(255, 255, 255, 30), width=1)
    d.line((m + pad_x, m + divider_y, m + pad_x + 22 * u, m + divider_y), fill=GOLD, width=1)

    # Text layer (+ keycaps), with a soft dark shadow for legibility on any scene.
    text = Image.new("RGBA", size, (0, 0, 0, 0))
    td = ImageDraw.Draw(text)
    for kind, a in cv.ops:
        if kind == "cap":
            x1, y1, x2, y2, r = a
            td.rounded_rectangle((m + x1, m + y1, m + x2, m + y2), radius=r,
                                 fill=KEYCAP, outline=KEYCAP_EDGE, width=1)
        elif kind == "rect":
            x1, y1, x2, y2, fill = a
            td.rectangle((m + x1, m + y1, m + x2, m + y2), fill=fill)
        else:
            x, y, s, font, fill, trk = a
            _draw_text(td, m + x, m + y, s, font, fill, trk)

    strength = 0.55 + 0.45 * (1 - backdrop)  # stronger shadow when there's less panel
    alpha = text.getchannel("A").filter(ImageFilter.GaussianBlur(max(1.0, 1.6 * u)))
    alpha = alpha.point(lambda v: min(255, int(v * 1.6 * strength)))
    shadow = Image.new("RGBA", size, (0, 0, 0, 0))
    shadow.putalpha(alpha)
    img.alpha_composite(shadow, (0, max(1, round(u))))
    img.alpha_composite(text)

    opacity = float(settings.get("opacity", 1.0))
    if opacity < 1.0:
        a = img.getchannel("A").point(lambda v: int(v * opacity))
        img.putalpha(a)
    return img
