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
import sys

import fsutil  # Windows/OneDrive-safe renames and folder wipes

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
COLORMAP = os.path.join(ROOT, "game", "tools", "dmd_colormap.json")
VERSION = "6"            # bump when the colouring changes: the cache (.cache/dmd_hd) keys on it
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


def _serum_init(crom):
    global _serum
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import serum
    _serum = serum.Serum(crom)


def scale_indices(vals, w, h, f):
    """Rows of colour indices (or shades) doubled by Scale2x until f times larger (2, 4, 8)."""
    rows = [list(vals[y * w:(y + 1) * w]) for y in range(h)]
    while f > 1:
        rows, f = scale2x(rows), f // 2
    return rows


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
    def cost(c):
        cs = c[0]
        return (sum(1 for a, b in zip(sh, cs) if a and a != b), sum(1 for a, b in zip(sh, cs) if b and not a))
    return min(caps, key=cost)


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
    folder, dst, f, crom_key, cache, source = job
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
                                  str(CAPTURE_HIDDEN).encode(), source.encode()] + srcs)).hexdigest()
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
    entry = None
    if by_cap:
        # the shade colours count the capture's Serum frames too (the dots where it shows other shades, its
        # text, left out)
        for sh, cs, fid, exact in by_cap.values():
            same = bytes(v if (v == c or not exact) else 0 for v, c in zip(sh, cs))
            found.append((same, s.colorize_frame(same, fid), s.palette(fid), True))
    if found or near:
        pal = shade_colours(found + [v[:3] for v in near.values()], palette(deff))
        os.makedirs(dst, exist_ok=True)
        ids = []
        for k, (n, (sh, idx, fpal, fid)) in enumerate(zip(names, shaded)):
            if idx is not None:
                img = rgb_image(scale_indices(idx, w, h, f), fpal)
                ids.append(fid)
            elif k in by_cap:
                sh, cs, fid, exact = by_cap[k]
                cidx, cpal = colorize_capture(s, sh, cs, fid, exact, pal)
                img = rgb_image(scale_indices(cidx, w, h, f), cpal)
                ids.append(fid)
            elif k in near:
                img = rgb_image(scale_indices(sh, w, h, f), shade_colours([near[k][:3]], pal))
                ids.append(near[k][3])
            else:
                img = rgb_image(scale_indices(sh, w, h, f), pal)
            img.save(os.path.join(dst, n), compress_level=6)
        exact = len(found) - len(by_cap)
        entry = {"palette": palette_hex(pal), "source": "serum", "serum_frames": exact,
                 "capture_frames": len(by_cap),
                 "near_frames": len(near), "shade_frames": len(frames) - exact - len(by_cap) - len(near),
                 "serum_ids": [min(ids), max(ids)]}
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


def serum_build(folders, dst_root, scale, crom, cache=None, processes=None):
    """{folder name: palettes.json entry} of the effects whose frames the Serum file knows, written in
    dst_root (serum_deff); the others are left to the PuP-hue colouring."""
    import multiprocessing
    with open(crom, "rb") as fp:
        crom_key = hashlib.sha1(fp.read()).hexdigest()
    data = os.path.join(ROOT, "game", "tron", "media_data.json")
    sources = json.load(open(data, encoding="utf-8"))["deffs"] if os.path.exists(data) else {}
    jobs = [(fo, os.path.join(dst_root, os.path.basename(fo)), scale, crom_key, cache,
             sources.get(str(int(os.path.basename(fo).split("_")[1])), {}).get("source", "")) for fo in folders]
    with multiprocessing.Pool(processes or os.cpu_count() or 2, initializer=_serum_init, initargs=(crom,)) as pool:
        entries = pool.map(serum_deff, jobs, chunksize=1)
    return {os.path.basename(fo): e for fo, e in zip(folders, entries) if e is not None}


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


def build(src_root, dst_root, scale, cache=None, processes=None, crom=None):
    """Every effect frame (f*.png) of src_root (game/media/dmd) upscaled in colour into dst_root (same
    names); the letter sprites stay out (tron/letter_panel.gd draws them: text). crom: the Serum
    colourisation (serum_build) for the effects it knows. Returns the frame count."""
    import glob
    from PIL import Image
    import dmd_hd
    cmap = load_colormap()
    tpal = text_palette(cmap)
    fsutil.remove_dir(dst_root)
    folders = sorted(glob.glob(os.path.join(src_root, "deff_*")))
    masks = text_masks()
    jobs, palettes = [], {}
    by_serum = serum_build(folders, dst_root, scale, crom, cache, processes) if crom and os.path.exists(crom) else {}
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
        text_frames = 0
        for p in frames:
            fname = os.path.basename(p)
            grey = dmd_hd.grey(Image.open(p))
            mask = frame_text_dots(masks[deff], grey) if deff in masks else None
            text_frames += mask is not None
            fpal = flat_palette(pal) if deff not in masks and is_flat(grey) else pal
            jobs.append((p, os.path.join(dst_root, name, fname), fpal, tpal, mask, scale, cache))
        if text_frames:
            palettes[name]["text_frames"] = text_frames
    os.makedirs(dst_root, exist_ok=True)
    with open(os.path.join(dst_root, "palettes.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump({"scale": scale, "text": palette_hex(tpal), "deffs": palettes,
                   "serum": os.path.basename(crom) if by_serum else None}, f, indent=0, sort_keys=True)
    if not jobs:
        return sum(e["serum_frames"] + e["capture_frames"] + e["near_frames"] + e["shade_frames"]
                   for e in by_serum.values())
    if len(jobs) < 8:
        done = len([color_file(j) for j in jobs])
    else:
        import multiprocessing
        with multiprocessing.Pool(processes or os.cpu_count() or 2) as pool:
            done = len(pool.map(color_file, jobs, chunksize=4))
    return done + sum(e["serum_frames"] + e["capture_frames"] + e["near_frames"] + e["shade_frames"]
                      for e in by_serum.values())


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
