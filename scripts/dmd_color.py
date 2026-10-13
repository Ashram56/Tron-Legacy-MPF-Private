#!/usr/bin/env python3
"""Colour for the HD DMD: the 16 shades of each display effect's animation mapped to colours, as a colour
DMD (Serum-style colourisation) does, at build time (scripts/gen_media.py build_color_frames).

The colour map, game/tools/dmd_colormap.json (small, tracked):
- "default": the Tron palette of effects without their own (cyan light lines to a white highlight);
- "text": the palette of text baked into an effect's pictures (dark blue, as the HD text drawn live);
- "deffs": {deff: {"hues": [main, accent], ...}} measured on the PuP-Pack video each effect plays with
  (scripts/pup_colormap.py, which also records the capture, the videos and the measured hues).
A palette is 16 colours (ramp): shade 0 black; the dim shades 1-7 (the ROM's film clips and backgrounds)
in the main hue, getting brighter; the bright shades 12-15 (the foreground: lines, objects, logos) in the
accent hue, getting lighter, 15 almost white (the highlight). The art never uses shades 8-11; they blend.

The colour frames are 2x (COLOR_SCALE, 256x64): Scale2x (EPX) on the shades, each dot 2x2 with diagonal
edges one step finer, every shade then in its colour, shown with nearest filtering (crisp dots). At
scale 8 they are upscaled as the HD grey frames are instead (scripts/dmd_hd.py: one smoothed mask per
shade, laid over the lower ones in the shade's colour), smoother but softer in busy film clips.
Text: an effect played from the emulator's capture shows its ROM text lines inside the picture (and the
status panel left of x 41 when the deff draws it). Each line is drawn with the ROM font at its layout
(scripts/rom_layout.py); in each frame that shows it (TEXT_MATCH of its dots lit, TEXT_BG of the black
cells or outlines around them dark), its lit dots take the text palette, as do the panel's lit dots. A
captured frame drawn in a single shade is a text screen (GAME OVER, BALL SAVED, TILT): all text. Other
frames in a single shade (logos, line art: DAFT PUNK) keep their top shades coloured (flat_palette).

Serum (this branch): with the Serum colourisation serum/trn_174h.cRZ (scripts/serum.py), an effect frame
the colourisation knows (by its CRC, as PinMAME finds it) takes the colours of the Serum frame instead:
its own 64 colours per dot (cframes, dynamic zones by shade, sprites), doubled by Scale2x on the colour
indices. A frame it does not know (the art without the score or text the ROM draws over it: the colour DMD
shows a frame with its text) takes the Serum frame of the effect's emulator capture (reference_capture.gif,
the screen PinMAME shows, text and panel included) that shows the same picture: each capture frame is found
in the colourisation by its CRC as PinMAME finds it, or, when none is (the capture prints values of other
lengths than the colourist's game: JACKPOT=00), by its screen (serum.Serum.fit). The effect frame is then
coloured by that Serum frame as libserum colours it (its art by shade in the dynamic zones, the rest in the
frame's own colours); where the capture differs from it (its text and panel, drawn live here) its lit dots
take the effect's shade colours and the rest is black (colorize_capture). A capture frame that shows over
CAPTURE_HIDDEN of the effect frame's lit dots dark (another moment, a wipe's mask) is not used. A frame
with no capture frame is compared with every Serum frame (serum.Serum.nearest); when one is the same
art (correlation NEAR_MIN and up), the frame takes its shade colours: per shade, the colour that frame's
dots of the shade have most often. Other frames of an effect with known or near frames take the effect's
shade colours (the same, over all of them). Only an effect with neither keeps its PuP-hue palette above.
Serum frames can show art of their own (a photo of Flynn, a new logo): exact frames show it, near frames
keep the ROM's art in the Serum colours. palettes.json records each effect's source ("serum", or "pup" /
"default") and its serum, capture, near and shade frame counts.

    .venv/bin/python scripts/dmd_color.py DEFF IN.png OUT.png [scale]   # one classic frame in DEFF's colours (2 or 8)
"""
import colorsys
import hashlib
import json
import os
import re
import sys

import fsutil  # Windows/OneDrive-safe renames and folder wipes

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
COLORMAP = os.path.join(ROOT, "game", "tools", "dmd_colormap.json")
VERSION = "8"            # bump when the colouring changes: the cache (.cache/dmd_hd) keys on it
TEXT_MATCH = 0.9
COLOR_SCALE = 2          # colour frames: 2x (Scale2x, crisp, 256x64), the default; 8 = the smooth per-shade filter

# The film's palette only: blue and cyan light lines, red / red-orange for CLU, Rinzler and the Recognizer, white
# highlights (the top shade) and black. No green, violet or yellow: the PuP videos have big green or amber text
# and graphics that are not the film's colours, so measured hues of those kinds are folded into these (ALIASES).
HUES = {"cyan": 188, "blue": 212, "deep blue": 232, "red": 2, "orange": 14}
ALIASES = {"green": "blue", "violet": "deep blue", "amber": "orange", "yellow": "orange"}
# (shade, saturation, value) of the main hue (dim shades) and of the accent hue (bright shades)
DIM = ((1, 1.0, 0.22), (4, 1.0, 0.55), (7, 0.92, 0.85))
BRIGHT = ((12, 0.95, 0.92), (13, 0.75, 1.0), (14, 0.45, 1.0), (15, 0.1, 1.0))


def load_colormap(path=COLORMAP):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_colormap(data, path=COLORMAP):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=1, sort_keys=True)
        f.write("\n")


def hue_of(name):
    return HUES[ALIASES.get(name, name)] if isinstance(name, str) else float(name)


def ramp(main, accent=None, dim=DIM, bright=BRIGHT):
    """16 (r, g, b) bytes: shade 0 black, the dim stops in the main hue, the bright ones in the accent hue
    (main if none), the shades between stops mixed in RGB (no rainbow between two hues)."""
    hm, ha = hue_of(main) / 360, hue_of(accent if accent is not None else main) / 360
    stops = [(0, (0.0, 0.0, 0.0))] + [(k, colorsys.hsv_to_rgb(hm, s, v)) for k, s, v in dim] \
        + [(k, colorsys.hsv_to_rgb(ha, s, v)) for k, s, v in bright]
    gap = abs(hm - ha) * 360
    if min(gap, 360 - gap) > 60:
        # a warm body and cool light lines: mixing them in RGB gives purple/magenta mid shades, which the
        # film never shows, so the shades after the last dim stop start again in the accent hue
        stops.append((dim[-1][0] + 1, colorsys.hsv_to_rgb(ha, 0.95, 0.5)))
    out = []
    for shade in range(16):
        a = max((st for st in stops if st[0] <= shade), key=lambda st: st[0])
        b = min((st for st in stops if st[0] >= shade), key=lambda st: st[0], default=a)
        t = 0 if b[0] == a[0] else (shade - a[0]) / (b[0] - a[0])
        out.append(tuple(round((x + (y - x) * t) * 255) for x, y in zip(a[1], b[1])))
    return out


def palette(deff, cmap=None):
    """The 16 colours of a display effect: its own (PuP hues) or the default."""
    cmap = cmap or load_colormap()
    entry = cmap["deffs"].get(str(deff)) or cmap["default"]
    return ramp(*entry["hues"][:2])


def text_palette(cmap=None):
    cmap = cmap or load_colormap()
    t = cmap["text"]
    return ramp(*t["hues"][:2], dim=[tuple(x) for x in t.get("dim", DIM)], bright=[tuple(x) for x in t.get("bright", BRIGHT)])


def palette_hex(pal):
    return ["#%02x%02x%02x" % c for c in pal]


def scale2x(rows):
    """Scale2x (EPX), the pixel-art doubling: rows of values -> rows twice as wide and high. Each dot becomes
    2x2; a corner takes the neighbours' value where two neighbours agree across it (a diagonal edge), so
    staircases get one step finer while every flat area and one-dot line stays crisp and exact."""
    h, w = len(rows), len(rows[0])
    out = [[0] * (2 * w) for _ in range(2 * h)]
    for y in range(h):
        up, row, down = rows[max(0, y - 1)], rows[y], rows[min(h - 1, y + 1)]
        for x in range(w):
            p = row[x]
            a, d = up[x], down[x]
            c, b = row[max(0, x - 1)], row[min(w - 1, x + 1)]
            e0 = e1 = e2 = e3 = p
            if c != b and a != d:
                e0 = a if c == a else p
                e1 = b if a == b else p
                e2 = c if d == c else p
                e3 = d if b == d else p
            out[2 * y][2 * x], out[2 * y][2 * x + 1] = e0, e1
            out[2 * y + 1][2 * x], out[2 * y + 1][2 * x + 1] = e2, e3
    return out


def upscale_color_2x(img, pal, text_pal=None, text_dots=None):
    """A classic effect frame -> 'RGB' frame 2x larger (COLOR_SCALE): Scale2x on the 16 shades (text dots
    as their own values, so text edges stay text), each shade then drawn in its palette colour. Shown
    with nearest filtering: crisp dots, no blur."""
    from PIL import Image
    import dmd_hd
    grey = dmd_hd.grey(img)
    w, h = grey.size
    g = grey.tobytes()
    t = text_dots if (text_dots is not None and text_pal is not None) else bytes(w * h)
    vals = [min(15, round(v / 17)) + (16 if v and m else 0) for v, m in zip(g, t)]
    big = scale2x([vals[y * w:(y + 1) * w] for y in range(h)])
    lut = [tuple(pal[k]) for k in range(16)] + [tuple((text_pal or pal)[k]) for k in range(16)]
    out = Image.new("RGB", (2 * w, 2 * h))
    out.putdata([lut[v] for row in big for v in row])
    return out


def upscale_color(img, pal, f, text_pal=None, text_dots=None):
    """A classic effect frame -> 'RGB' frame f times larger, coloured shade by shade: the same level sets
    as dmd_hd.upscale_levels (each "dot >= shade" mask smoothed), each one laid over the lower ones in its
    shade's colour, so an edge blends the two colours it separates. text_dots ('L' 128x32 mask): the dots
    drawn in the text palette."""
    from PIL import Image
    import dmd_hd
    grey = dmd_hd.grey(img)
    size = (grey.width * f, grey.height * f)
    out = Image.new("RGB", size, (0, 0, 0))
    weight = None
    if text_pal is not None and text_dots is not None and text_dots.getbbox():
        weight = dmd_hd.upscale_levels(text_dots, f)
    for v in sorted(c for _, c in (grey.getcolors(256) or []) if c):
        shade = min(15, round(v / 17))
        fill = Image.new("RGB", size, tuple(pal[shade]))
        if weight is not None:
            fill = Image.composite(Image.new("RGB", size, tuple(text_pal[shade])), fill, weight)
        out = Image.composite(fill, out, dmd_hd.smooth_mask(grey.point(lambda p, v=v: 255 if p >= v else 0), f))
    return out


# ---------------------------------------------------------------------- text inside the pictures

PANEL_X = 41            # the status panel (scores, separator) left of this column, in captures that show it
FLAT = 0.95
TEXT_BG = 0.8           # share of a line's glyph cells (outline, plain cell) that must be dark


def text_masks(deff_ids=None):
    """{deff: {"lines": [(text dots, cell dots), ...], "panel": bool}} for every effect that plays the
    emulator's capture: each ROM text line drawn with its font at its layout (lists of 4096 booleans, 128 x
    32: the glyph dots, and the dark dots of the glyph cells or outlines around them), and whether the
    capture shows the status panel (rom_layout.status_panel_deffs)."""
    import csv
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import gen_fonts
    import gen_media
    import rom_layout
    data = json.load(open(os.path.join(ROOT, "game", "tron", "media_data.json"), encoding="utf-8"))["deffs"]
    rows = {int(r["deff"]): r for r in csv.DictReader(open(os.path.join(gen_media.PKG, "event_map.csv"),
                                                           encoding="utf-8"))}
    _, get, _ = gen_fonts.decode_all()
    fonts = json.load(open(os.path.join(ROOT, "game", "fonts", "fonts.json"), encoding="utf-8"))["fonts"]
    calls = rom_layout.deff_calls()
    panels = rom_layout.status_panel_deffs()
    out = {}
    for key, info in data.items():
        deff = int(key)
        if info["source"] != "reference" or (deff_ids is not None and deff not in deff_ids):
            continue
        lines = gen_media.text_lines(gen_media.ROM_TEXT.get(deff, rows.get(deff, {}).get("rom_text", "")))
        lines = [ln for ln in lines if "%" not in ln]
        masks = []
        for line, lay in zip(lines, rom_layout.line_layouts(deff, lines, fonts, calls.get(deff, [])) if lines else []):
            if not lay:
                continue
            canvas = gen_fonts.render(get, fonts[lay["font"]], line, lay["x"], lay["y"], lay["flags"],
                                      [[-1] * 128 for _ in range(32)])
            fg = [v > 0 for row in canvas for v in row]
            bg = [v == 0 for row in canvas for v in row]
            if any(fg):
                masks.append((fg, bg))
        out[deff] = {"lines": masks, "panel": deff in panels}
    return out


def is_flat(grey):
    """A frame drawn in one shade (FLAT of its lit dots right of the panel): a text screen or line art."""
    counts = {}
    for i, v in enumerate(grey.tobytes()):
        if v and i % 128 >= PANEL_X:
            counts[v] = counts.get(v, 0) + 1
    return not counts or max(counts.values()) >= FLAT * sum(counts.values())


def frame_text_dots(spec, grey):
    """The text dots of one classic frame of a captured effect ('L' greys) as 128x32 'L' bytes, or None:
    every lit dot of a frame in one shade (a text screen: BALL SAVED, GAME OVER, TILT, ...); else the lit
    dots of each text line the frame shows (TEXT_MATCH of its glyph dots lit, TEXT_BG of its cell dark),
    and the lit dots of the status panel."""
    lit = [p > 0 for p in grey.tobytes()]
    if is_flat(grey):
        return bytes(255 if t else 0 for t in lit) if any(lit) else None
    text = [False] * len(lit)
    for fg, bg in spec["lines"]:
        n_fg, n_bg = sum(fg), sum(bg)
        on = sum(1 for a, b in zip(fg, lit) if a and b)
        dark = sum(1 for a, b in zip(bg, lit) if a and not b)
        if on >= TEXT_MATCH * n_fg and (not n_bg or dark >= TEXT_BG * n_bg):
            text = [t or (a and b) for t, a, b in zip(text, fg, lit)]
    if spec["panel"]:
        text = [t or (b and i % 128 < PANEL_X) for i, (t, b) in enumerate(zip(text, lit))]
    return bytes(255 if t else 0 for t in text) if any(text) else None


def flat_palette(pal):
    """The palette of line art drawn in one shade (a logo): the top shades kept coloured, not white."""
    return list(pal[:13]) + [pal[13]] * 3


# ---------------------------------------------------------------------- Serum

SERUM = os.path.join(ROOT, "serum", "trn_174h.cRZ")
_serum = None


_v2 = ({}, None, "")    # serum_v2's export: (index, zip, key), per worker


def _serum_init(crom):
    global _serum, _v2
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import serum
    import serum_v2
    _serum = serum.Serum(crom)
    index, z = serum_v2.load()
    _v2 = (index, z, hashlib.sha1(json.dumps(index, sort_keys=True).encode()).hexdigest() if index else "")


# ---------------------------------------------------------------------- Serum v2 (256x64)

V2_PAD = 1              # dots round the live text's line boxes also blanked in a v2 picture (its HD lettering)
V2_CAPTURE_PAD = 2      # dots round what only the capture frame shows (its text, its panel) blanked


def v2_source(deff, name, shades, caps, source):
    """(index entry, shades of the 128x32 frame it colours) of the 256x64 picture of an effect frame from the Serum
    v2 export (scripts/serum_v2.py): the frame's own when the colourisation knows it, else that of the capture frame
    that shows it (closest_capture: the colourisation knows the ROM's screens with their text and panel). None."""
    import serum_v2
    index = _v2[0]
    e = index.get("%s/%s" % (deff, name))
    if e and e["sha"] == serum_v2.shades_key(shades):
        return e, shades
    lit = sum(1 for a in shades if a)
    if not lit:
        return None
    known = [(cs, index["%s/cap%04d" % (deff, k)]) for k, cs in enumerate(caps) if "%s/cap%04d" % (deff, k) in index]
    if not known:
        return None
    cs, e = min(known, key=lambda c: closest_cost(shades, c[0]))
    if sum(1 for a, c in zip(shades, cs) if a and a != c) > CAPTURE_HIDDEN * lit:
        return None                     # another moment of the animation (or a wipe's mask)
    if source == "reference" and any(a != c for i, (a, c) in enumerate(zip(shades, cs)) if i % 128 >= PANEL_X):
        return None                     # the frame is a capture frame: only the same one shows it
    return e, cs


def _grow(dots, pad):
    out = set()
    for k in dots:
        x, y = k % 128, k // 128
        for j in range(max(0, y - pad), min(32, y + pad + 1)):
            for i in range(max(0, x - pad), min(128, x + pad + 1)):
                out.add(j * 128 + i)
    return out


def v2_picture(entry, shades, src, text):
    """(256x64 picture, colour of each live text line) of an effect frame from its v2 picture (v2_source; src: the
    shades of the frame the picture colours). Black where HD draws text live (the recorded lines' boxes, grown by
    V2_PAD: the colourist's own lettering there goes), where only the capture frame shows something (its text and
    its status panel, grown by V2_CAPTURE_PAD), and on a text screen (one lit shade right of the panel) every dot
    the ROM leaves dark away from its lit dots (the colourisation's own lettering and credits). Each line's colour:
    the most common colour of the picture under the line's ROM-lit dots."""
    from collections import Counter
    import serum_v2
    img = serum_v2.picture(_v2[1], entry)
    px = img.load()
    text = text or {}
    dots = set(text.get("dots", ()))
    cols, blank = [], set()
    for x0, y0, x1, y1 in text.get("lines", ()):
        inside = [k for k in dots if x0 <= k % 128 <= x1 and y0 <= k // 128 <= y1]
        seen = Counter(px[2 * (k % 128) + i, 2 * (k // 128) + j] for k in inside for i in (0, 1) for j in (0, 1))
        seen = [(n, c) for c, n in seen.items() if sum(c) > 30]
        cols.append("#%02x%02x%02x" % max(seen)[1] if seen else None)
        blank |= _grow({y * 128 + x for y in range(max(0, y0), min(32, y1 + 1))
                        for x in range(max(0, x0), min(128, x1 + 1))}, V2_PAD)
    blank |= _grow(dots, V2_PAD)
    blank |= _grow({k for k in range(4096) if src[k] and not shades[k]}, V2_CAPTURE_PAD)
    lit = {shades[k] for k in range(4096) if shades[k] and k % 128 >= PANEL_X}
    if len(lit) <= 1:
        near = _grow({k for k in range(4096) if shades[k]}, 1)
        blank |= {k for k in range(4096) if k not in near}
    for k in blank:
        x, y = 2 * (k % 128), 2 * (k // 128)
        for i in (0, 1):
            for j in (0, 1):
                px[x + i, y + j] = (0, 0, 0)
    return img, cols


def scale2x_serum(vals, shades, w, h):
    """libserum's 2x upscale of a colourised frame (libframeutil Scale2xPreserve, SERUM_SCALING_SCALE2X, the default
    of every v1 colourisation): Scale2x on the colour indices, outside the frame counting as no neighbour, except
    that a dot the ROM lit (shades) never takes a neighbour the ROM left dark: the result is the union of Scale2x
    and line doubling, so the ROM's five-dot letters keep every dot. Rows of indices 2w x 2h."""
    out = [[0] * (2 * w) for _ in range(2 * h)]
    for y in range(h):
        for x in range(w):
            k = y * w + x
            e = vals[k]
            b = vals[k - w] if y > 0 else None
            hh = vals[k + w] if y + 1 < h else None
            d = vals[k - 1] if x > 0 else None
            f = vals[k + 1] if x + 1 < w else None
            o = [e, e, e, e]
            if b != hh and d != f:
                pick = [(k - 1 if x > 0 else None) if d == b else k, (k + 1 if x + 1 < w else None) if b == f else k,
                        (k - 1 if x > 0 else None) if d == hh else k, (k + 1 if x + 1 < w else None) if hh == f else k]
                for n, src in enumerate(pick):
                    if src == k:
                        continue
                    if shades[k] and (src is None or not shades[src]):
                        continue                    # never round a lit dot away into emptiness
                    o[n] = vals[src] if src is not None else 0
            out[2 * y][2 * x], out[2 * y][2 * x + 1] = o[0], o[1]
            out[2 * y + 1][2 * x], out[2 * y + 1][2 * x + 1] = o[2], o[3]
    return out


def scale_indices(vals, w, h, f, shades=None):
    """Rows of colour indices (or shades) doubled until f times larger (2, 4, 8): libserum's own upscale
    (scale2x_serum) when the ROM's shades are given, else Scale2x."""
    if shades is not None and f == 2:
        return scale2x_serum(list(vals), shades, w, h)
    rows = [list(vals[y * w:(y + 1) * w]) for y in range(h)]
    while f > 1:
        rows, f = scale2x(rows), f // 2
    return rows


def line_colour(vals, lut, shades, dots):
    """The colour a text line is shown in: of its dots (indices k), the most common colour among those in its
    brightest shade, as "#rrggbb"; None when none is lit or all are black."""
    from collections import Counter
    lit = [k for k in dots if shades[k]]
    if not lit:
        return None
    top = max(shades[k] for k in lit)
    counts = Counter(tuple(lut[vals[k]]) for k in lit if shades[k] == top)
    counts = Counter({c: n for c, n in counts.items() if sum(c) > 30}) or counts
    c = counts.most_common(1)[0][0]
    return "#%02x%02x%02x" % c if sum(c) > 30 else None


def clear_text(vals, lut, shades, text, blank=()):
    """A colour frame's text drawn live in HD (frame_text: text = {"dots": [k, ...], "lines": [[x0, y0, x1, y1], ...]}
    of the frame) taken out of the picture: (indices with those dots black, palette, shades with them dark, the
    colour of each line as the colourisation shows it). blank: dots also shown black (text_blanks). Unchanged
    without either."""
    text = text or {}
    if not text.get("dots") and not blank:
        return vals, lut, shades, []
    dots = set(text.get("dots", ()))
    cols = [line_colour(vals, lut, shades, [k for k in dots if x0 <= k % 128 <= x1 and y0 <= k // 128 <= y1])
            for x0, y0, x1, y1 in text.get("lines", ())]
    lut = list(lut) + [(0, 0, 0)]
    black = len(lut) - 1
    dots |= set(blank)
    vals = [black if k in dots else v for k, v in enumerate(vals)]
    shades = bytes(0 if k in dots else v for k, v in enumerate(shades))
    return vals, lut, shades, cols


def text_blanks(shades, texts):
    """The dots of a recorded effect's frame (shades) the colour picture shows black, so that all its text is the
    HD's own (drawn live in the clean font): where the ROM leaves them dark, every dot of a text screen (a frame in
    one shade, or none: the colourisation's own lettering, credits, the text of another blink phase), and in other frames
    the dots inside the boxes of the lines the effect shows in any of its frames (texts: {frame: text})."""
    lit = [k for k in range(4096) if shades[k] and k % 128 >= PANEL_X]
    levels = {shades[k] for k in lit}
    if len(levels) <= 1:
        return [k for k in range(4096) if not shades[k]]
    boxes = {tuple(b) for t in texts.values() for b in t.get("lines", ())}
    return [y * 128 + x for x0, y0, x1, y1 in boxes for y in range(max(0, y0), min(32, y1 + 1))
            for x in range(max(0, x0), min(128, x1 + 1)) if not shades[y * 128 + x]]


def rgb_image(rows, lut):
    from PIL import Image
    img = Image.new("RGB", (len(rows[0]), len(rows)))
    img.putdata([tuple(lut[v]) for row in rows for v in row])
    return img


def shade_colours(found, fallback):
    """The 16 colours of an effect's shades from its Serum frames [(shades, colour indices, palette[, by
    capture]), ...]: per shade, the colour its dots have most often (the fallback palette for a shade never
    seen); shade 0 is black. Frames coloured through their capture (by capture true) do not count the lit dots
    their Serum frame leaves black: its colours there are of the capture's screen, not of the frame's art."""
    from collections import Counter
    counts = [Counter() for _ in range(16)]
    for item in found:
        shades, idx, pal = item[:3]
        skip_dark = len(item) > 3 and item[3]
        for v, c in zip(shades, idx):
            col = pal[c]
            if skip_dark and v and 0.3 * col[0] + 0.59 * col[1] + 0.11 * col[2] <= 20:
                continue
            counts[v][col] += 1
    # shade 0 is the ROM's black: kept black (a Serum frame's own background art is not the effect's)
    return [(0, 0, 0)] + [counts[k].most_common(1)[0][0] if counts[k] else tuple(fallback[k]) for k in range(1, 16)]


PKG_DMD = os.path.join(ROOT, "assets", "mpf_package", "media", "dmd")


def capture_path(deff):
    """The emulator capture of an effect (reference_capture.gif of the asset package), or None."""
    import glob
    found = glob.glob(os.path.join(PKG_DMD, "deff_%03d_*" % deff, "reference_capture.gif"))
    return found[0] if found else None


def capture_serum(s, path):
    """[(shades, Serum frame id, by CRC), ...] of the capture's frames that the colourisation knows: by CRC
    (libserum's search, from a reset), else, for a capture none of whose frames it knows by CRC, by screen
    (Serum.fit)."""
    import serum
    from PIL import Image, ImageSequence
    frames = [serum.shades(f.convert("RGBA")) for f in ImageSequence.Iterator(Image.open(path))]
    s.reset()
    out = []
    for sh in frames:
        fid = s.identify(sh)
        if fid != serum.NO_FRAME and s.activeframes[fid]:
            out.append((sh, fid, True))
    if not out:
        for sh in frames:
            fid, _ = s.fit(sh)
            if fid != serum.NO_FRAME and s.activeframes[fid]:
                out.append((sh, fid, False))
    return out


CAPTURE_HIDDEN = 0.25   # share of a frame's lit dots that its capture frame may show dark (its text's boxes)


def closest_capture(sh, caps):
    """The (shades, id, by CRC) of caps that shows sh: fewest of sh's lit dots in another shade, then fewest
    dots lit in the capture only (its text)."""
    return min(caps, key=lambda c: closest_cost(sh, c[0]))


def closest_cost(sh, cs):
    """How far a capture frame cs is from showing a frame sh (closest_capture)."""
    return (sum(1 for a, b in zip(sh, cs) if a and a != b), sum(1 for a, b in zip(sh, cs) if b and not a))


def colorize_capture(s, sh, cap, fid, exact, shade_pal):
    """A frame's colour indices and palette from the Serum frame fid of its capture frame cap: libserum's
    colours (dynamic zones by the frame's shades, sprites). The capture shows the ROM's screen, its text and
    panel (drawn live here) included. Found by CRC (exact): where it differs from the frame, and where it
    shows text lit inside a box the frame has lit and it shows dark (a wipe, a cleared box), the frame's lit
    dots take the effect's shade colours, the others are black. Outside the dynamic zones the Serum frame's
    own colours are of the capture's screen: dots the frame leaves dark are black, and its lit dots keep the
    Serum colour where that is not black and the capture was found by CRC, else take the shade colours.
    Palette: the frame's 64 colours, then the 16 shade colours (indices 64-79)."""
    px = s.width * s.height
    idx = s.colorize_frame(sh, fid)
    for hit in s.find_sprites(sh, fid):
        s.draw_sprite(idx, hit)
    pal = s.palette(fid)
    dark = [0.3 * r + 0.59 * g + 0.11 * b <= 20 for r, g, b in pal]
    black = min(range(len(pal)), key=lambda c: sum(pal[c]))
    dm = s.dynamasks[fid * px:(fid + 1) * px]
    w, h = s.width, s.height
    hidden = [bool(a and not c) for a, c in zip(sh, cap)]

    def in_box(k):
        # a dot the capture shows lit inside a box of the frame it shows dark: the ROM's text over a wipe or a
        # cleared box (drawn live here), not the frame's art
        y, x = divmod(k, w)
        return sum(hidden[yy * w + xx] for yy in range(max(0, y - 2), min(h, y + 3))
                   for xx in range(max(0, x - 2), min(w, x + 3))) >= 4

    for k in range(px):
        if exact and (cap[k] != sh[k] or (sh[k] and in_box(k))):
            # the capture's text and panel (drawn live here) or another moment of the art
            idx[k] = s.nccolors + sh[k] if sh[k] else black
        elif dm[k] != 255:
            continue
        elif not sh[k]:
            idx[k] = black
        elif not exact or dark[idx[k]]:
            idx[k] = s.nccolors + sh[k]
    return idx, list(pal) + [tuple(c) for c in shade_pal]


def serum_deff(job):
    """(folder, dst folder, scale, crom sha1, cache dir, media_data source) -> palettes.json entry of the effect,
    its frames written in Serum colours; None when the colourisation knows none of its frames or of its
    capture's (writes nothing)."""
    import glob
    import serum
    from PIL import Image
    folder, dst, f, crom_key, cache, source, texts = job
    frames = sorted(glob.glob(os.path.join(folder, "f*.png")))
    if not frames:
        return None
    deff = int(os.path.basename(folder).split("_")[1])
    cap_path = capture_path(deff)
    srcs = []
    for p in frames + ([cap_path] if cap_path else []):
        with open(p, "rb") as fp:
            srcs.append(fp.read())
    key = hashlib.sha1(b"|".join([b"serum", VERSION.encode(), crom_key.encode(), str(f).encode(),
                                  str(serum.NEAR_MIN).encode(), str(serum.FIT_MAX).encode(),
                                  str(CAPTURE_HIDDEN).encode(), source.encode(), _v2[2].encode(),
                                  str((V2_PAD, V2_CAPTURE_PAD)).encode(),
                                  json.dumps(texts, sort_keys=True).encode()] + srcs)).hexdigest()
    cached = os.path.join(cache, "serum_" + key) if cache else None
    names = [os.path.basename(p) for p in frames]
    if cached and os.path.exists(os.path.join(cached, "entry.json")):
        entry = json.load(open(os.path.join(cached, "entry.json"), encoding="utf-8"))
        if entry is not None:
            os.makedirs(dst, exist_ok=True)
            for n in names:
                fsutil.copy_file(os.path.join(cached, n), os.path.join(dst, n))
        return entry
    s = _serum
    s.reset()
    w, h = s.width, s.height
    shaded, found = [], []
    for p in frames:
        sh = serum.shades(Image.open(p))
        fid = s.identify(sh)
        if fid != serum.NO_FRAME and s.activeframes[fid]:
            idx = s.colorize_frame(sh, fid)
            for hit in s.find_sprites(sh, fid):
                s.draw_sprite(idx, hit)
            shaded.append((sh, idx, s.palette(fid), fid))
            found.append((sh, idx, s.palette(fid)))
        else:
            shaded.append((sh, None, None, None))
    caps = capture_serum(s, cap_path) if cap_path and any(v[1] is None for v in shaded) else []
    by_cap, near = {}, {}
    for k, (sh, idx, _, _) in enumerate(shaded):
        if idx is not None or not any(sh):
            continue
        cap = closest_capture(sh, caps) if caps else None
        if cap and sum(1 for a, c in zip(sh, cap[0]) if a and not c) > CAPTURE_HIDDEN * sum(1 for a in sh if a):
            cap = None                      # the capture frame hides much of it: another moment (or a wipe's mask)
        if cap and source == "reference" and any(a != c for i, (a, c) in enumerate(zip(sh, cap[0]))
                                                  if i % 128 >= PANEL_X):
            cap = None                      # the frame is a capture frame: only the same one shows it
        if cap and cap[2]:                  # a capture frame PinMAME finds by its CRC: the screen itself
            by_cap[k] = (sh,) + cap
            continue
        fid, corr = s.nearest(sh)
        if fid != serum.NO_FRAME and corr >= serum.NEAR_MIN:
            near[k] = (sh, s.colorize_frame(sh, fid), s.palette(fid), fid)
        elif cap:                           # the capture's screen found by fit(): the frame's own art is not
            by_cap[k] = (sh,) + cap
    # the Serum v2 pictures (256x64 art), where the export has one for the frame or its capture frame
    v2src = [None] * len(shaded)
    if _v2[0] and f == 2 and any(k.startswith(os.path.basename(folder) + "/") for k in _v2[0]):
        from PIL import ImageSequence
        cap_all = [serum.shades(c.convert("RGBA")) for c in ImageSequence.Iterator(Image.open(cap_path))] \
            if cap_path else []
        v2src = [v2_source(os.path.basename(folder), n, sh, cap_all, source) for n, (sh, _, _, _) in zip(names, shaded)]
    entry = None
    if by_cap:
        # the shade colours count the capture's Serum frames too (the dots where it shows other shades, its
        # text, left out)
        for sh, cs, fid, exact in by_cap.values():
            same = bytes(v if (v == c or not exact) else 0 for v, c in zip(sh, cs))
            found.append((same, s.colorize_frame(same, fid), s.palette(fid), True))
    if found or near or any(v2src):
        pal = shade_colours(found + [v[:3] for v in near.values()], palette(deff))
        os.makedirs(dst, exist_ok=True)
        ids, line_colours = [], {}
        for k, (n, (sh, idx, fpal, fid)) in enumerate(zip(names, shaded)):
            if idx is not None:
                vals, lut = idx, fpal
                ids.append(fid)
            elif k in by_cap:
                sh, cs, fid, exact = by_cap[k]
                vals, lut = colorize_capture(s, sh, cs, fid, exact, pal)
                ids.append(fid)
            elif k in near:
                vals, lut = sh, shade_colours([near[k][:3]], pal)
                ids.append(near[k][3])
            else:
                vals, lut = sh, pal
            if v2src[k]:
                img, cols = v2_picture(v2src[k][0], sh, v2src[k][1], texts.get(n))
            else:
                vals, lut, sh, cols = clear_text(vals, lut, sh, texts.get(n), text_blanks(sh, texts))
                img = rgb_image(scale_indices(vals, w, h, f, sh), lut)
            if cols:
                line_colours[n] = cols
            img.save(os.path.join(dst, n), compress_level=6)
        exact = len(found) - len(by_cap)
        entry = {"palette": palette_hex(pal), "source": "serum", "serum_frames": exact,
                 "capture_frames": len(by_cap),
                 "near_frames": len(near), "shade_frames": len(frames) - exact - len(by_cap) - len(near),
                 "v2_frames": sum(1 for v in v2src if v),
                 "serum_ids": [min(ids), max(ids)] if ids else [], "text_colors": line_colours}
    if cached:
        tmp = cached + ".%d.tmp" % os.getpid()
        os.makedirs(tmp, exist_ok=True)
        if entry is not None:
            for n in names:
                fsutil.copy_file(os.path.join(dst, n), os.path.join(tmp, n))
        with open(os.path.join(tmp, "entry.json"), "w", encoding="utf-8") as fp:
            json.dump(entry, fp)
        try:
            os.replace(tmp, cached)
        except OSError:
            # another worker cached the same effect (same key, same frames) first
            fsutil.remove_dir(tmp)
    return entry


def serum_build(folders, dst_root, scale, crom, cache=None, processes=None, texts=None):
    """{folder name: palettes.json entry} of the effects whose frames the Serum file knows, written in
    dst_root (serum_deff); the others are left to the PuP-hue colouring. texts: {folder name: {frame file: text}}
    (recorded_text), taken out of the pictures (clear_text)."""
    import multiprocessing
    with open(crom, "rb") as fp:
        crom_key = hashlib.sha1(fp.read()).hexdigest()
    data = os.path.join(ROOT, "game", "tron", "media_data.json")
    sources = json.load(open(data, encoding="utf-8"))["deffs"] if os.path.exists(data) else {}
    jobs = [(fo, os.path.join(dst_root, os.path.basename(fo)), scale, crom_key, cache,
             sources.get(str(int(os.path.basename(fo).split("_")[1])), {}).get("source", ""),
             (texts or {}).get(os.path.basename(fo), {})) for fo in folders]
    with multiprocessing.Pool(processes or os.cpu_count() or 2, initializer=_serum_init, initargs=(crom,)) as pool:
        entries = pool.map(serum_deff, jobs, chunksize=1)
    return {os.path.basename(fo): e for fo, e in zip(folders, entries) if e is not None}


# ---------------------------------------------------------------------- Serum sprites

# The sprites the game draws over its effects: the ZUSE / TRON target letters (tron/letter_panel.gd: solid at
# full level, hollow at level 2, x 42 + 21 * i) and the Flynn's Arcade reel (tron/arcade_reel.gd: cabinets at
# y 0, award icons at y 5, scrolling from x 82). {deff: (y, kind of each file)}; the reel's x is any place
# inside it (its Serum frames colour the whole reel by shade).
SPRITE_DEFFS = {91: 5, 92: 5, 94: 1, 107: 5, 105: None}
LETTER_SETS = {91: "zuse", 92: "zuse", 94: "zuse", 107: "tron"}
REEL_X = 54
SHOWN = 0.9             # share of a sprite's lit dots its capture must show in the same shades: drawn there


def sprite_shades(path):
    """(width, height, [shade or None (transparent)]) of a sprite: letters' hollow images are drawn at level
    UNLIT 2 (gen_media.UNLIT_LEVEL), other pictures by their greys."""
    from PIL import Image
    im = Image.open(path).convert("RGBA")
    hollow = os.path.basename(path).startswith("hollow")
    out = []
    for r, g, b, a in im.getdata():
        if not a:
            out.append(None)
        else:
            v = min(15, round(r / 17))
            out.append(2 if hollow and v else v)
    return im.width, im.height, out


def sprite_place(deff, name, w):
    """(x, y) of a sprite in its effect's 128x32 frame."""
    if deff == 105:
        return (REEL_X, 0) if name.startswith("cabinet") else (REEL_X + 8, 5)
    i = int(name[-5])
    return 42 + 21 * i, SPRITE_DEFFS[deff]


def colour_sprite(s, spr, x, y, base, fid):
    """The colours of a sprite's dots (None: transparent) drawn at (x, y) over base (shades) in Serum frame
    fid, as libserum colours that screen; and the share of its lit dots not black."""
    w, h, sh = spr
    frame = bytearray(base)
    for j in range(h):
        for i in range(w):
            v = sh[j * w + i]
            if v is not None and 0 <= x + i < s.width and 0 <= y + j < s.height:
                frame[(y + j) * s.width + x + i] = v
    idx = s.colorize_frame(bytes(frame), fid)
    pal = s.palette(fid)
    cols, lit, seen = [], 0, 0
    for j in range(h):
        for i in range(w):
            v = sh[j * w + i]
            inside = 0 <= x + i < s.width and 0 <= y + j < s.height
            c = tuple(pal[idx[(y + j) * s.width + x + i]]) if inside and v is not None else None
            cols.append(c if v is not None else None)
            if v:
                lit += 1
                seen += bool(c) and sum(c) > 0
    return cols, seen / lit if lit else 0.0


def sprite_build(src_root, dst_root, crom, scale=COLOR_SCALE):
    """The sprites of SPRITE_DEFFS in their Serum colours, scale times larger (Scale2x), with their
    transparency, into dst_root (same names). Each picture (the same image in several effects is coloured
    once) takes the colours of the capture frame of its effects that shows it (SHOWN of its dots), else of
    the capture's Serum frame with it drawn in (the arcade reel: one colour ramp by shade). Letters not shown
    by a capture frame found by CRC, and pictures none colours (SHOWN of their lit dots not black), take shade
    by shade the colours of the letters of their set and kind, else of their kind (TRON's solid letters:
    ZUSE's). Returns {"deff_NNN/name":
    {"serum_id", "how"}}."""
    import glob
    from collections import Counter, defaultdict
    from PIL import Image
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import serum
    s = serum.Serum(crom)
    caps = {d: capture_serum(s, capture_path(d)) if capture_path(d) else [] for d in SPRITE_DEFFS}
    files = defaultdict(list)            # image bytes -> [(deff, name)]
    for d in SPRITE_DEFFS:
        for p in sorted(glob.glob(os.path.join(src_root, "deff_%03d" % d, "*.png"))):
            name = os.path.basename(p)
            if name.startswith("f") and name[1:-4].isdigit():
                continue
            with open(p, "rb") as fp:
                files[fp.read()].append((d, name))
    done, info = {}, {}
    for data, uses in files.items():
        d0, n0 = uses[0]
        spr = sprite_shades(os.path.join(src_root, "deff_%03d" % d0, n0))
        w, h, sh = spr
        best = None
        for d, name in uses:
            x, y = sprite_place(d, name, w)
            for cap, fid, by_crc in caps[d]:
                lit = [(j, i) for j in range(h) for i in range(w) if sh[j * w + i]]
                same = sum(1 for j, i in lit if 0 <= x + i < 128 and 0 <= y + j < 32
                           and cap[(y + j) * 128 + x + i] == sh[j * w + i])
                shown = bool(lit) and same >= SHOWN * len(lit)
                cols, ok = colour_sprite(s, spr, x, y, cap, fid)
                key = (shown, ok)
                if best is None or key > best[0]:
                    best = (key, cols, fid, by_crc)
        if best and best[0][1] >= SHOWN:
            done[data] = (best[1], best[2], ("capture" if best[3] else "screen") if best[0][0] else "placed")
        else:
            done[data] = None
    # letters shown by a capture frame the colourisation finds by CRC keep its colours dot by dot; the others
    # (found by screen only: the colourist's letters may be collected where the capture's are not) take, shade
    # by shade, the colours of their set's letters of their kind, and so do the pictures none colours (TRON's
    # solid letters: those of ZUSE's); a kind none colours keeps its greys
    def group(d, name):
        kind = re.sub(r"\d*\.png$", "", name)
        return (LETTER_SETS.get(d, d), kind), kind

    tables = defaultdict(lambda: defaultdict(Counter))
    for data, uses in files.items():
        if done[data]:
            d, name = uses[0]
            sh = sprite_shades(os.path.join(src_root, "deff_%03d" % d, name))[2]
            for key in group(d, name):
                for v, c in zip(sh, done[data][0]):
                    if v and c:
                        tables[key][v][c] += 1
    for data, uses in files.items():
        d, name = uses[0]
        if done[data] and (d not in LETTER_SETS or done[data][2] == "capture"):
            continue
        sh = sprite_shades(os.path.join(src_root, "deff_%03d" % d, name))[2]
        own, kind = group(d, name)
        table = tables.get(own) or tables.get(kind) or {}
        cols = [None if v is None else (0, 0, 0) if not v else
                (table[v].most_common(1)[0][0] if v in table else (17 * v,) * 3) for v in sh]
        fid = done[data][1] if done[data] else None
        done[data] = (cols, fid, done[data][2] if done[data] else "shades")
    for data, uses in files.items():
        d, name = uses[0]
        w, h, sh = sprite_shades(os.path.join(src_root, "deff_%03d" % d, name))
        cols, fid, how = done[data]
        lut = sorted({c for c in cols if c})
        vals = [0 if c is None else 1 + lut.index(c) for c in cols]
        rows = scale_indices(vals, w, h, scale)
        rgba = [(0, 0, 0, 0)] + [c + (255,) for c in lut]
        img = Image.new("RGBA", (len(rows[0]), len(rows)))
        img.putdata([rgba[v] for row in rows for v in row])
        for d, name in uses:
            os.makedirs(os.path.join(dst_root, "deff_%03d" % d), exist_ok=True)
            img.save(os.path.join(dst_root, "deff_%03d" % d, name), compress_level=6)
            info["deff_%03d/%s" % (d, name)] = {"serum_id": fid, "how": how}
    return info


# ---------------------------------------------------------------------- build

def color_file(job):
    """(src classic png, dst, palette, text palette, text dots (frame_text_dots) or None, scale, cache dir):
    writes the colour HD frame dst, through the cache (keyed on the picture, the palettes and the dots)."""
    import shutil
    from PIL import Image
    import dmd_hd
    src, dst, pal, text_pal, mask, f, cache = job
    with open(src, "rb") as fp:
        data = fp.read()
    key = hashlib.sha1(b"|".join([b"color", VERSION.encode(), dmd_hd.VERSION.encode(), str(dmd_hd.SIGMA).encode(),
                                  str(dmd_hd.CUT).encode(), str(f).encode(), json.dumps([pal, text_pal]).encode(),
                                  mask or b"-", data])).hexdigest()
    cached = os.path.join(cache, key + ".png") if cache else None
    if cached and os.path.exists(cached):
        shutil.copyfile(cached, dst)
        return dst
    img = Image.open(src)
    if f == 2:
        upscale_color_2x(img, pal, text_pal, mask).save(dst, compress_level=6)
    else:
        dots = Image.frombytes("L", img.size, mask) if mask else None
        upscale_color(img, pal, f, text_pal, dots).save(dst, compress_level=6)
    if cached:
        os.makedirs(cache, exist_ok=True)
        tmp = cached + ".%d.tmp" % os.getpid()
        shutil.copyfile(dst, tmp)
        fsutil.replace_cached(tmp, cached)    # another worker may hold the same entry (Windows)
    return dst


def fallback_frame(job):
    """(src classic png, dst, palette, text or None, scale): an effect frame the colourisation does not know, in
    its effect's shade palette (the PuP-hue or default ramp), its live text taken out; returns its lines' colours
    in the text palette."""
    from PIL import Image
    import serum
    src, dst, pal, text, f, tpal = job
    sh = serum.shades(Image.open(src))
    vals, lut, sh2, _ = clear_text(sh, pal, sh, text)
    cols = [("#%02x%02x%02x" % tuple(tpal[15])) for _ in (text or {}).get("lines", [])]
    rgb_image(scale_indices(vals, 128, 32, f, sh2), lut).save(dst, compress_level=6)
    return cols


def recorded_text(src_root, recorded):
    """{folder name: {frame file: {"dots": [k], "lines": [[x0, y0, x1, y1], ...]}}}: the ROM text HD draws live over
    the recorded effects' frames (scripts/frame_text.py: the lines of media/dmd_hd/text.json), as dots of the
    128x32 frame (the lit dots its cleared copy leaves dark, the rectangles drawn as such left in) and each line's
    box."""
    import glob
    from PIL import Image
    import frame_text
    import serum
    fonts = {f["id"]: f for f in json.load(open(os.path.join(ROOT, "game", "fonts", "fonts.json"),
                                                encoding="utf-8"))["fonts"]}
    frames = sorted(glob.glob(os.path.join(src_root, "deff_*", "f*.png")))
    found = frame_text.process_files(frames, os.path.join(ROOT, ".cache", "frame_text"), recorded)
    out = {}
    for src, (lines, boxes, cleared) in found.items():
        if not cleared or not lines:
            continue
        a, c = serum.shades(Image.open(src)), serum.shades(Image.open(cleared))
        kept = set()
        for x0, y0, x1, y1, _, solid in boxes:
            for y in range(y0, y1 + 1):
                for x in range(x0, x1 + 1):
                    if solid or x in (x0, x1) or y in (y0, y1):
                        kept.add(y * 128 + x)
        dots = [k for k in range(4096) if a[k] and not c[k] and k not in kept]
        rows = []
        for ln in lines:
            m = fonts.get(int(ln[1]), {"ascent": 7, "descent": 1})
            x0 = int(ln[2])
            rows.append([x0, int(ln[3]) - int(m["ascent"]) + 1, x0 + int(ln[5]) - 1, int(ln[3]) + int(m["descent"])])
        out.setdefault(os.path.basename(os.path.dirname(src)), {})[os.path.basename(src)] = {"dots": dots, "lines": rows}
    return out


def build(src_root, dst_root, scale=COLOR_SCALE, cache=None, processes=None, crom=None, recorded=None):
    """Every effect frame (f*.png) of src_root (game/media/dmd) in colour, scale times larger, into dst_root (same
    names): the Serum colourisation (crom, serum_build) for the effects it knows, and the sprites drawn over them
    (sprite_build: letters, the arcade reel) in its colours; the others in their effect's shade palette. The text HD
    draws live over the recorded effects (recorded: their folder names, recorded_text) is taken out of the pictures
    and its colour kept per line. Returns the info written to dst_root/palettes.json."""
    import glob
    cmap = load_colormap()
    tpal = text_palette(cmap)
    fsutil.remove_dir(dst_root)
    os.makedirs(dst_root, exist_ok=True)
    folders = sorted(glob.glob(os.path.join(src_root, "deff_*")))
    texts = recorded_text(src_root, set(recorded or ()))
    by_serum = serum_build(folders, dst_root, scale, crom, cache, processes, texts) \
        if crom and os.path.exists(crom) else {}
    jobs, palettes = [], {}
    for folder in folders:
        name = os.path.basename(folder)
        deff = int(name.split("_")[1])
        frames = sorted(glob.glob(os.path.join(folder, "f*.png")))
        if name in by_serum:
            palettes[name] = by_serum[name]
            continue
        pal = palette(deff, cmap)
        palettes[name] = {"palette": palette_hex(pal), "source": "pup" if str(deff) in cmap["deffs"] else "default"}
        if not frames:
            continue
        os.makedirs(os.path.join(dst_root, name), exist_ok=True)
        for p in frames:
            n = os.path.basename(p)
            jobs.append(((p, os.path.join(dst_root, name, n), pal, texts.get(name, {}).get(n), scale, tpal), name, n))
    if jobs:
        import multiprocessing
        with multiprocessing.Pool(processes or os.cpu_count() or 2) as pool:
            cols = pool.map(fallback_frame, [j[0] for j in jobs], chunksize=4)
        for (_, name, n), c in zip(jobs, cols):
            if c:
                palettes[name].setdefault("text_colors", {})[n] = c
    sprites = sprite_build(src_root, dst_root, crom, scale) if by_serum and scale == COLOR_SCALE else {}
    info = {"scale": scale, "text": palette_hex(tpal), "deffs": palettes, "sprites": sprites,
            "serum": os.path.basename(crom) if by_serum else None}
    with open(os.path.join(dst_root, "palettes.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(info, f, indent=0, sort_keys=True)
    return info


# ---------------------------------------------------------------------- the effects' data in colour

def capture_colours(s, deff):
    """[(shades, colour indices, palette), ...] of an effect's emulator capture as the colourisation shows it: the
    frames libserum finds by CRC, from a reset (sprites drawn in), else the screens fit() finds."""
    path = capture_path(deff)
    if not path:
        return []
    v2 = capture_colours_v2(deff, path)
    if v2:
        return v2
    out = []
    for sh, fid, _ in capture_serum(s, path):
        idx = s.colorize_frame(sh, fid)
        for hit in s.find_sprites(sh, fid):
            s.draw_sprite(idx, hit)
        out.append((sh, idx, s.palette(fid)))
    return out


def capture_colours_v2(deff, path):
    """capture_colours from the Serum v2 export (scripts/serum_v2.py), when it has the capture's frames: each dot's
    colour the brightest of its 2x2 pixels in the 256x64 picture (as (shades, dot numbers, a colour per dot))."""
    import serum
    import serum_v2
    from PIL import Image, ImageSequence
    index, z = serum_v2.load()
    out = []
    for k, f in enumerate(ImageSequence.Iterator(Image.open(path))):
        e = index.get("deff_%03d/cap%04d" % (deff, k))
        if not e:
            continue
        px = serum_v2.picture(z, e).load()
        cols = [max((px[2 * (d % 128) + i, 2 * (d // 128) + j] for i in (0, 1) for j in (0, 1)), key=sum)
                for d in range(4096)]
        out.append((serum.shades(f.convert("RGBA")), range(4096), cols))
    return out


def _region(it, fonts, panel):
    """The dots (k) where an effect item draws: a text line's rows and the columns its alignment can reach (left of
    the status panel's separator or right of it), a rectangle's box (a bar's full reach)."""
    if it["type"] == "rect":
        x0, y0 = it["x"], it["y"]
        w, h = max(it["w"], 1), max(it["h"], 1)
        if it["name"].startswith("Bar"):
            w, h = (10, 1) if it["h"] == 1 else (1, 10)
            if it["w"] == 1:                      # vertical bars grow upwards from their y
                y0 = {"BarZfs": 0, "BarClu": 11, "BarGem": 22}.get(it["name"], y0)
        return [y * 128 + x for y in range(y0, min(32, y0 + h)) for x in range(x0, min(128, x0 + w))]
    m = fonts.get(it["font"], {"ascent": 7, "descent": 1})
    y0, y1 = it["y"] - int(m["ascent"]) + 1, it["y"] + int(m["descent"])
    x, flags = it["x"], it["flags"]
    lo, hi = (x - 50, x + 50) if flags & 2 else ((x - 90, x) if flags & 4 else (x, x + 90))
    if panel:
        lo, hi = (max(lo, PANEL_X), hi) if x >= PANEL_X else (lo, min(hi, PANEL_X - 2))
    return [y * 128 + xx for y in range(max(0, y0), min(32, y1 + 1)) for xx in range(max(0, lo), min(128, hi + 1))]


def item_colour(caps, dots, level=None):
    """The colour the colourisation gives an item's dots over an effect's capture frames: per frame, its lit dots
    in the region in the item's level (else the region's brightest shade), the most common colour of all."""
    from collections import Counter
    counts = Counter()
    for sh, idx, pal in caps:
        lit = [k for k in dots if sh[k]]
        if not lit:
            continue
        want = level if level and any(sh[k] == level for k in lit) else max(sh[k] for k in lit)
        for k in lit:
            if sh[k] == want:
                c = tuple(pal[idx[k] % len(pal)])
                if sum(c) > 30:
                    counts[c] += 1
    return "#%02x%02x%02x" % counts.most_common(1)[0][0] if counts else None


def annotate(media_root, dst_root, info, crom):
    """The effects' data (media_root/deff_NNN/effect.json, scripts/gen_media.py) told their colours, read by
    tron/dmd_effect.gd when the colour is on (HD): the frames item's "color_frames" (the colour pictures, frame for
    frame; checksum-identical pictures share one file), a text line's "color" and a rectangle's "color_rgb" (the
    colourisation's colours of the effect's capture there; else the same item's colour in the other effects), the
    letters' "color_pic" and the arcade reel's "color_*" pictures (sprite_build). dst_root/text_colors.json: the
    colour of each line of text HD draws live over a recorded frame. Returns the number of effects told colours."""
    import glob
    from collections import Counter, defaultdict
    from PIL import Image
    import serum
    s = serum.Serum(crom) if crom and os.path.exists(crom) else None
    fonts = {f["id"]: f for f in json.load(open(os.path.join(ROOT, "game", "fonts", "fonts.json"),
                                                encoding="utf-8"))["fonts"]}
    res = "res://media/"
    color_res = res + os.path.basename(dst_root) + "/"
    effects = {}
    for path in sorted(glob.glob(os.path.join(media_root, "deff_*", "effect.json"))):
        with open(path, encoding="utf-8") as f:
            effects[path] = json.load(f)
    # item colours measured on the captures, then the same item's colour elsewhere for the effects without one
    measured, by_name = {}, defaultdict(Counter)
    for path, eff in effects.items():
        deff = int(os.path.basename(os.path.dirname(path)).split("_")[1])
        caps = capture_colours(s, deff) if s else []
        panel = any(it["type"] == "panel" for it in eff["items"])
        for i, it in enumerate(eff["items"]):
            if it["type"] not in ("text", "rect") or it.get("name") in ("Background", "PanelClear") \
                    or it["name"].startswith("Clear") or (it["type"] == "rect" and not it.get("level")):
                continue
            c = item_colour(caps, _region(it, fonts, panel), it.get("level") if it["type"] == "rect" else None)
            if c:
                measured[(path, i)] = c
                by_name[(it["type"], it["name"])][c] += 1
    any_text = Counter()
    for (kind, _), cnt in by_name.items():
        if kind == "text":
            any_text.update(cnt)
    # colour pictures: one file per distinct picture
    shared, moved, told = {}, {}, 0
    for path, eff in effects.items():
        folder = os.path.dirname(path)
        name = os.path.basename(folder)
        own = {}
        for p in sorted(glob.glob(os.path.join(folder, "f*.png"))):
            own[hashlib.md5(Image.open(p).convert("RGBA").tobytes()).hexdigest()] = os.path.basename(p)
        changed = False
        for i, it in enumerate(eff["items"]):
            if it["type"] == "frames":
                twins = []
                for pic, ms in it["frames"]:
                    rel = pic[len(res) + len("dmd/"):]
                    digest = hashlib.md5(Image.open(os.path.join(media_root, rel)).convert("RGBA").tobytes()).hexdigest()
                    mine = own.get(digest)
                    cpath = os.path.join(dst_root, name, mine) if mine else None
                    if cpath in moved:
                        twins.append(color_res + moved[cpath])
                        continue
                    if not cpath or not os.path.exists(cpath):
                        twins = None
                        break
                    with open(cpath, "rb") as f:
                        key = hashlib.sha1(f.read()).hexdigest()
                    first = moved[cpath] = shared.setdefault(key, name + "/" + mine)
                    if first != name + "/" + mine:
                        os.remove(cpath)
                    twins.append(color_res + first)
                if twins:
                    it["color_frames"] = twins
                    changed = True
            elif it["type"] in ("text", "rect") and ((path, i) in measured or by_name.get((it["type"], it["name"]))):
                c = measured.get((path, i)) or by_name[(it["type"], it["name"])].most_common(1)[0][0]
                it["color" if it["type"] == "text" else "color_rgb"] = c
                changed = True
            elif it["type"] == "text" and any_text and it["name"].startswith("Line"):
                it["color"] = any_text.most_common(1)[0][0]
                changed = True
            elif it["type"] == "letters":
                for sp in it["sprites"]:
                    rel = sp["pic"][len(res) + len("dmd/"):]
                    if os.path.exists(os.path.join(dst_root, rel)):
                        sp["color_pic"] = color_res + rel
                        changed = True
            elif it["type"] == "arcade":
                for k in ("cabinets", "icons_a", "icons_b"):
                    pics = [color_res + p[len(res) + len("dmd/"):] for p in it[k]]
                    if all(os.path.exists(os.path.join(dst_root, p[len(color_res):])) for p in pics):
                        it["color_" + k] = pics
                        changed = True
        if changed:
            told += 1
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                json.dump(eff, f, indent=1)
                f.write("\n")
    lines = {}
    for name, entry in info["deffs"].items():
        for n, cols in entry.get("text_colors", {}).items():
            lines[name + "/" + n] = cols
    with open(os.path.join(dst_root, "text_colors.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(lines, f, indent=0, sort_keys=True)
    return told


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    from PIL import Image
    import dmd_hd
    f = int(argv[3]) if len(argv) > 3 else COLOR_SCALE
    img = Image.open(argv[1])
    (upscale_color_2x(img, palette(int(argv[0]))) if f == 2 else upscale_color(img, palette(int(argv[0])), f)).save(argv[2])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
