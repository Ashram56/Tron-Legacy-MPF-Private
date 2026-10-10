"""DMD screens drawn the way the ROM draws them: text in a ROM font at a dot position, and ROM images.

A screen is a list of draw items, sent to GMC as the event arg `draw` and drawn by tron/service_screen.gd:
- text(t, font, x, y, flags, level): text_draw_str (y = baseline row; flags 1 left edge at x, 2 centred on x,
  4 right edge at x), in a ROM font (game/fonts, scripts/gen_fonts.py), at a palette level (0-15, default 15);
- fit(t, x, y, fonts): text_draw_msg_fit, the first font of the list whose text width fits the display;
- image(n, x, y): bitmap_draw of ROM image n (assets/mpf_package/media/rom_images_all.zip), top left at x, y;
- box(x, y, w, h, level): a filled rectangle at a palette level (0-15).
Widths come from game/fonts/fonts.json as the ROM measures them (text_width); without the generated
fonts (unit tests before scripts/gen_media.py) a 6-dot advance per character stands in.
"""
import json
import os

FONTS_JSON = os.path.join(os.path.dirname(__file__), "..", "fonts", "fonts.json")
WIDTH = 128
_FONTS = None


def fonts():
    global _FONTS
    if _FONTS is None:
        _FONTS = {}
        if os.path.exists(FONTS_JSON):
            with open(FONTS_JSON, encoding="utf-8") as f:
                _FONTS = {int(font["id"]): font for font in json.load(f)["fonts"]}
    return _FONTS


def text_width(font, s):
    """text_width: glyph widths and offsets plus the font spacing between glyphs (missing glyphs skipped)."""
    m = fonts().get(font)
    if not m:
        return 6 * len(s) - 1 if s else 0
    gs = [m["glyphs"][c] for c in s if c in m["glyphs"]]
    return sum(g["w"] + g["xoff"] + m["spacing"] for g in gs) - m["spacing"] if gs else 0


def text(t, font, x=64, y=0, flags=2, level=15):
    item = {"t": str(t), "f": font, "x": x, "y": y, "a": flags}
    if level != 15:
        item["l"] = level
    return item


def fit(t, x=64, y=0, fonts_list=(2, 0), flags=2, width=WIDTH):
    """text_draw_msg_fit: the first font of the list in which the text fits `width` dots (else the last)."""
    t = str(t)
    for font in fonts_list:
        if text_width(font, t) <= width:
            break
    return text(t, font, x, y, flags)


def image(n, x, y):
    return {"i": n, "x": x, "y": y}


def box(x, y, w, h, level=15):
    return {"r": [x, y, w, h], "l": level}


def lines_of(draw):
    """The texts of a draw list, top to bottom (rows, then left to right): what the screen says."""
    items = sorted((d for d in draw if "t" in d and d["t"]), key=lambda d: (d["y"], d["x"]))
    return [d["t"] for d in items]
