#!/usr/bin/env python3
"""Finds the ROM-font text in recorded display effect frames, for the HD display mode's clean fonts.

The effects shown from the emulator's reference capture (scripts/gen_media.py, source "reference") have
their text baked into the 128x32 frames, drawn by the ROM in its own fonts. This finds each line of it:
a run of glyphs of one ROM font (game/fonts/rom_font_NN.png: white = lit dot, opaque black = the cell's
cleared dots, transparent = not drawn) that matches the frame exactly, dot for dot, at one level, with
the ROM's spacing between glyphs (gen_fonts.render). Letters cut by the frame's edge or covered by other
art do not match and stay part of the picture.

The HD frames (game/media/dmd_hd) are made with the found letters' lit dots cleared (clear_text), and
game/tools/dmd_mode.gd draws each line live in the clean font over them (game/media/dmd_hd/text.json:
per deff folder and frame file, [text, font id, x of the line's left dot, baseline row, level, width,
first character shown, characters shown, and for a zoomed line its zoom and clip's left: complete_lines,
ZOOMS).
The classic frames keep the recorded text.

    python scripts/frame_text.py deff_001 [...]      # prints the lines found in each frame
"""
import hashlib
import json
import os
import sys

import fsutil  # Windows/OneDrive-safe renames

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
GAME = os.path.join(ROOT, "game")
MIN_SINGLE = 14        # a run of one glyph counts only when it lights this many dots (digits, big letters)
SKIP_FONTS = {42, 43}  # shaded digit fonts: drawn as pictures, not text
LONE_OK = set("0123456789ABCDEFGHJKMNOPQRSTUVWXYZ")
THIN = set("I1")
SIGNS = ".,:;'-!/"
# Effects whose text zooms in (blocky, sparse enlargements of the text the last frame shows, not ROM-font
# text): in HD the zoom frames lose everything right of keep_left (their only art is the text) and show
# the source frame's lines drawn `zoom` times larger about their middle, clipped to the right of keep_left
# (0: no text yet). deff 100 (ZEN rollover): the ROM shows a few scattered blocks, then ZEN at about twice
# its size, then ZEN; HD shows nothing, then ZEN closing in from 3 times its size.
ZOOMS = {"deff_100": {"source": "f006.png", "keep_left": 42,
                      "zoom": {"f000.png": 0, "f001.png": 0, "f002.png": 0, "f003.png": 3, "f004.png": 2.25,
                               "f005.png": 1.5}}}
VERSION = "1"          # bump when the matching changes: the cache (.cache/frame_text) keys on it
_fonts = None


def load_fonts():
    """{font id: {"ascent", "spacing", "glyphs": {c: (w, h, xoff, below, lit [(dy, dx)], dark [(dy, dx)])}}}"""
    from PIL import Image
    meta = json.load(open(os.path.join(GAME, "fonts", "fonts.json"), encoding="utf-8"))["fonts"]
    out = {}
    for f in meta:
        fid = f["id"]
        if fid in SKIP_FONTS:
            continue
        atlas = Image.open(os.path.join(GAME, "fonts", "rom_font_%02d.png" % fid)).convert("RGBA")
        px = atlas.load()
        cells = {}
        for line in open(os.path.join(GAME, "fonts", "rom_font_%02d.fnt" % fid), encoding="utf-8"):
            if line.startswith("char id="):
                v = dict(kv.split("=") for kv in line.split()[1:])
                cells[chr(int(v["id"]))] = (int(v["x"]), int(v["y"]))
        glyphs = {}
        for c, g in f["glyphs"].items():
            if c not in cells:
                continue
            x0, y0 = cells[c]
            lit, dark = [], []
            for dy in range(g["h"]):
                for dx in range(g["w"]):
                    r, _, _, a = px[x0 + dx, y0 + dy]
                    if a:
                        (lit if r else dark).append((dy, dx))
            glyphs[c] = (g["w"], g["h"], g["xoff"], g["below"], lit, dark)
        out[fid] = {"ascent": f["ascent"], "descent": f["descent"], "spacing": f["spacing"], "glyphs": glyphs}
    return out


def levels(img):
    """32 rows of 128 levels (0-15) of a frame (its brightest channel)."""
    rgba = img.convert("RGBA")
    px = rgba.load()
    return [[(max(px[x, y][:3]) + 8) // 17 if px[x, y][3] >= 128 else 0 for x in range(img.width)]
            for y in range(img.height)]


def _fits(a, top, left, g):
    """The level of glyph g drawn with its top-left dot at (top, left) in a, or 0 when it does not match."""
    w, h, _, _, lit, dark = g
    if top < 0 or left < 0 or top + h > len(a) or left + w > len(a[0]):
        return 0
    lv = a[top + lit[0][0]][left + lit[0][1]] if lit else -1
    if lv == 0:
        return 0
    for dy, dx in lit:
        if a[top + dy][left + dx] != lv:
            return 0
    for dy, dx in dark:
        if a[top + dy][left + dx]:
            return 0
    return lv


def _anchor(g):
    """(row, width, care bits, lit bits, [don't-care bit values]) of glyph g's first row with a lit dot,
    over its first 8 columns: the pattern of lit dots a frame row must show where the glyph is."""
    w, h, _, _, lit, dark = g
    oy = lit[0][0]
    width = min(w, 8)
    lit_bits = sum(1 << dx for dy, dx in lit if dy == oy and dx < width)
    care = lit_bits | sum(1 << dx for dy, dx in dark if dy == oy and dx < width)
    free = [1 << dx for dx in range(width) if not care >> dx & 1]
    combos = [0]
    for bit in free:
        combos += [c | bit for c in combos]
    return oy, width, [lit_bits | c for c in combos]


def _index(a):
    """{(width, bits): [(row, left)]}: every place of a frame by the lit pattern of its next width dots."""
    out = {}
    for y, row in enumerate(a):
        nz = sum(1 << x for x, v in enumerate(row) if v)
        for x in range(len(row)):
            if nz >> x:
                for width in range(1, 9):
                    out.setdefault((width, (nz >> x) & ((1 << width) - 1)), []).append((y, x))
    return out


def find_glyphs(a, font, index=None):
    """{(pen x, baseline): [(char, level), ...]} of every glyph of font that matches a (spaces aside),
    the glyph with the most lit dots first (',' before the '.' it contains); glyphs drawn alike ('O' and
    '0') are both listed, for the run to choose."""
    index = index if index is not None else _index(a)
    hits = {}
    for c, g in font["glyphs"].items():
        w, h, xoff, below, lit, dark = g
        if not lit:
            continue
        if "anchor" not in font:
            font["anchor"] = {}
        if c not in font["anchor"]:
            font["anchor"][c] = _anchor(g)
        oy, width, patterns = font["anchor"][c]
        for bits in patterns:
            for y, left in index.get((width, bits), ()):
                top = y - oy
                lv = _fits(a, top, left, g)
                if lv:
                    hits.setdefault((left - xoff, top + h - 1 - below), []).append((c, lv))
    gl = font["glyphs"]
    for v in hits.values():
        v.sort(key=lambda h: (-len(gl[h[0]][4]), h[0]))
    return hits


def _pick(cands, gl, digits):
    """The glyph of a run among those matching at one place: the most lit dots, then a digit among
    digits and a letter among letters (the ROM draws 'O' and '0' alike)."""
    best = [c for c in cands if len(gl[c[0]][4]) == len(gl[cands[0][0]][4])]
    if len(best) > 1:
        best.sort(key=lambda h: (h[0].isdigit() != digits, h[0]))
    return best[0]


def runs(a, font, index=None):
    """[(text, x, baseline, level, lit dots [(y, x)], width)]: chains of matching glyphs at the ROM's
    spacing, on one baseline (a glyph one row off is taken too: the ROM's '#' sits a row high)."""
    hits = find_glyphs(a, font, index)
    gl = font["glyphs"]
    sp = font["spacing"]
    space = gl.get(" ")

    def at(pen, base, lv):
        """The glyphs at pen x on base (or a row off) of level lv: [(char, level, baseline)]."""
        out = []
        for b in (base, base - 1, base + 1):
            out += [(c, l, b) for c, l in hits.get((pen, b), []) if l == lv]
        return out

    def advance(c):
        g = gl[c]
        return g[0] + g[2] + sp

    followed = set()
    for (px, base), cands in hits.items():
        for c, lv in cands:
            followed.add((px + advance(c), base))
    out = []
    for start in sorted(hits, key=lambda k: (k[1], k[0])):
        if start in followed:
            continue
        lv0 = hits[start][0][1]
        base0 = start[1]
        # first pass: the chain of candidates; then each place's glyph, knowing whether the run is numeric
        chain, pen = [], start[0]
        while True:
            cands = at(pen, base0, lv0)
            if cands:
                cands.sort(key=lambda h: (-len(gl[h[0]][4]), h[2] != base0))
                chain.append((pen, cands))
                pen += advance(cands[0][0])
                continue
            if space and chain and chain[-1] != " ":
                after = pen + advance(" ")
                if at(after, base0, lv0) and _space_clear(a, (pen, base0), space):
                    chain.append(" ")
                    pen = after
                    continue
            break
        # 'O' or '0' (drawn alike): what the rest of its word is, a digit when nothing tells
        words, word = [], []
        for item in chain + [" "]:
            if item == " ":
                words.append(word)
                word = []
            else:
                word.append(item)
        picked = []
        for word in words:
            kinds = [{c.isdigit() for c, _, _ in cands if c.isalnum() and len(gl[c][4]) == len(gl[cands[0][0]][4])}
                     for _, cands in word]
            numeric = sum(k == {True} for k in kinds) >= sum(k == {False} for k in kinds)
            picked.append([(pen, _pick(cands, gl, numeric)) for pen, cands in word])
        # words of signs only at either end are bits of art
        while picked and not any(c.isalnum() for _, (c, _, _) in picked[-1]):
            picked.pop()
        while picked and not any(c.isalnum() for _, (c, _, _) in picked[0]):
            picked.pop(0)
        if not picked:
            continue
        text, dots = "", []
        for word in picked:
            text += " " if text else ""
            for pen, (c, _, b) in word:
                g = gl[c]
                top = b - g[1] + 1 + g[3]
                left = pen + g[2]
                dots += [(top + dy, left + dx) for dy, dx in g[4]]
                text += c
        x0 = picked[0][0][0]
        last_pen, (last, _, _) = picked[-1][-1]
        out.append((text, x0, base0, lv0, dots, last_pen + advance(last) - sp - x0))
    return out


def _space_clear(a, pos, space):
    w, h, xoff, below, lit, dark = space
    top = pos[1] - h + 1 + below
    left = pos[0] + xoff
    return all(0 <= top + dy < len(a) and 0 <= left + dx < len(a[0]) and not a[top + dy][left + dx]
               for dy, dx in dark)


def _keep(text, dots):
    """Whether a run is text: two letters or digits at least, not only thin strokes ('I', 'L', '1': bars
    and corners of the art match those), mostly letters or digits; or one big letter or digit."""
    letters = [c for c in text if c.isalnum()]
    signs = [c for c in text if c != " " and not c.isalnum()]
    if len(letters) >= 2:
        return not set(letters) <= THIN and len(signs) <= len(letters)
    return text in LONE_OK and len(dots) >= MIN_SINGLE


def frame_text(img, fonts):
    """The text lines of a frame: [(text, font id, x, baseline, level, width, lit dots)], biggest first,
    no two sharing a dot."""
    a = levels(img)
    index = _index(a)
    found = []
    for fid, font in fonts.items():
        for text, x, base, lv, dots, width in runs(a, font, index):
            if _keep(text, dots):
                found.append((len(dots), -fid, text, fid, x, base, lv, width, dots))
    found.sort(reverse=True)
    taken = set()
    out = []
    for _, _, text, fid, x, base, lv, width, dots in found:
        if taken.isdisjoint(dots):
            taken.update(dots)
            out.append((text, fid, x, base, lv, width, dots))
    return out


def _cached_fonts():
    global _fonts
    if _fonts is None:
        _fonts = load_fonts()
    return _fonts


def scan(job):
    """(src png, cache dir): frame_text of the frame, through the cache:
    [[text, font id, x, baseline, level, width, lit dots [[y, x]]]]."""
    from PIL import Image
    src, cache = job
    with open(src, "rb") as fp:
        data = fp.read()
    with open(os.path.join(GAME, "fonts", "fonts.json"), "rb") as fp:
        fonts_data = fp.read()
    key = hashlib.sha1(b"|".join([VERSION.encode(), hashlib.sha1(fonts_data).hexdigest().encode(), data])).hexdigest()
    meta = os.path.join(cache, key + ".json")
    if os.path.exists(meta):
        return json.load(open(meta, encoding="utf-8"))
    lines = [[t, fid, x, b, lv, w, [list(d) for d in dots]]
             for t, fid, x, b, lv, w, dots in frame_text(Image.open(src), _cached_fonts())]
    os.makedirs(cache, exist_ok=True)
    tmp = meta + ".%d.tmp" % os.getpid()
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(lines, f)
    fsutil.replace_cached(tmp, meta)
    return lines


def _pens(font, text, x):
    """The pen x of each glyph of text drawn from x (gen_fonts.render)."""
    gl, out = font["glyphs"], []
    for c in text:
        out.append(x)
        g = gl.get(c)
        if g:
            x += g[0] + g[2] + font["spacing"]
    return out


def _lone(t):
    """A run short enough to be a chance match: two letters or fewer, not a number."""
    letters = [c for c in t if c.isalnum()]
    return len(letters) <= 2 and not all(c.isdigit() for c in letters)


def complete_lines(frames, fonts):
    """The lines of one effect's frames ({frame path: scan result}), each partial line made whole: a line
    that is part of a longer line of the effect (same font and baseline) is shown as that line's part, at
    its place in it. Where the missing letters run off the frame (text sliding in), the whole line is drawn
    and the frame clips it; otherwise the letters from the first to the last the frame shows (a letter
    partly drawn, dissolving in or partly covered, counts when most of its dots are). Returns {path: (lines,
    dots to clear [(y, x, level)])}, a line being [text, font id, x, baseline, level, width, start, count]:
    the whole line, its left dot and width, and the characters shown (count from start); the dots of all
    the line's letters are cleared, shown or not."""
    from PIL import Image
    whole = {}
    for lines in frames.values():
        for t, fid, x, base, lv, w, _ in lines:
            whole.setdefault((fid, base), {}).setdefault(t, set()).add(x)
    for key, texts in whole.items():
        for t in list(texts):
            if any(t != u and t in u for u in texts):
                del texts[t]
    seen = {}
    for lines in frames.values():
        for t, fid, x, base, *_ in lines:
            seen[(t, fid, x, base)] = seen.get((t, fid, x, base), 0) + 1
    out = {}
    for name, lines in frames.items():
        res, clear, parts = [], [], {}
        a = levels(Image.open(name)) if lines else None
        for t, fid, x, base, lv, w, dots in lines:
            clear += [(y, x_, lv) for y, x_ in dots]
            font = fonts[fid]
            longer = [u for u in whole.get((fid, base), {}) if u != t and t in u]
            core = t.strip(SIGNS)
            if not longer and core and core != t:     # a sign at an end can be a bit of a covered letter
                longer = [u for u in whole.get((fid, base), {}) if u not in (core, t) and core in u]
                if longer:
                    x = _pens(font, t, x)[t.index(core)]
                    t = core
            if not longer and _lone(t) and seen[(t, fid, x, base)] < min(2, len(frames)):
                clear = clear[:len(clear) - len(dots)]  # two letters seen once: likely a bit of art
                continue
            if not longer:
                res.append([t, fid, x, base, lv, w, 0, len(t)])
                continue
            u = max(longer, key=len)
            places = [k for k in range(len(u) - len(t) + 1) if u.startswith(t, k)]
            # where the whole line would start: one the effect shows it at, else the first place
            starts = [(k, x - _pens(font, u, 0)[k]) for k in places]
            known = [s for s in starts if s[1] in whole[(fid, base)][u]]
            k, ux = (known or starts)[0]
            part = parts.setdefault((u, fid, ux, base, lv), set())
            part.update(range(k, k + len(t)))
        for (u, fid, ux, base, lv), matched in parts.items():
            font = fonts[fid]
            gl = font["glyphs"]
            pens = _pens(font, u, ux)
            uw = _pens(font, u + " ", ux)[-1] - font["spacing"] - ux

            def cell(i):
                """Glyph i's lit dots in the frame, and how many it has in all."""
                g = gl.get(u[i])
                if not g or not g[4]:
                    return [], 0
                top = base - g[1] + 1 + g[3]
                return [(top + dy, pens[i] + g[2] + dx) for dy, dx in g[4]
                        if 0 <= top + dy < 32 and 0 <= pens[i] + g[2] + dx < 128], len(g[4])

            shown = []
            for i in range(len(u)):
                dots, n = cell(i)
                clear += [(y, x, lv) for y, x in dots]
                on = sum(1 for y, x in dots if a[y][x] == lv)
                shown.append(i in matched or (n > 0 and 2 * on >= n))
            lo, hi = min(matched), max(matched)
            off = [len(cell(i)[0]) < cell(i)[1] for i in range(len(u))]   # letters the frame's edge cuts
            if (lo == 0 or any(off[:lo])) and (hi == len(u) - 1 or any(off[hi + 1:])):
                res.append([u, fid, ux, base, lv, uw, 0, len(u)])
                continue
            lo = shown.index(True)
            hi = len(shown) - shown[::-1].index(True)
            res.append([u, fid, ux, base, lv, uw, lo, hi - lo])
        out[name] = (res, clear)
    return out


def clear_text(img, dots):
    """A copy of img with dots [(y, x)] cleared to black."""
    out = img.convert("RGBA").copy()
    px = out.load()
    for y, x in dots:
        px[x, y] = (0, 0, 0, 255)
    return out


def _components(a):
    """The 4-connected runs of dots at one level of a frame: [(level, [(y, x)])]."""
    seen, out = set(), []
    for y in range(len(a)):
        for x in range(len(a[0])):
            if a[y][x] and (y, x) not in seen:
                lv, todo, comp = a[y][x], [(y, x)], []
                seen.add((y, x))
                while todo:
                    p = todo.pop()
                    comp.append(p)
                    for q in ((p[0] + 1, p[1]), (p[0] - 1, p[1]), (p[0], p[1] + 1), (p[0], p[1] - 1)):
                        if 0 <= q[0] < len(a) and 0 <= q[1] < len(a[0]) and q not in seen and a[q[0]][q[1]] == lv:
                            seen.add(q)
                            todo.append(q)
                out.append((lv, comp))
    return out


def shapes(a):
    """A frame's dots as rectangles [[x0, y0, x1, y1, level, filled]] (filled 1: a solid block, 0: a one-dot
    frame), or None when any part of it is not one (art)."""
    out = []
    for lv, comp in _components(a):
        ys, xs = [p[0] for p in comp], [p[1] for p in comp]
        y0, y1, x0, x1 = min(ys), max(ys), min(xs), max(xs)
        if len(comp) == (y1 - y0 + 1) * (x1 - x0 + 1):
            out.append([x0, y0, x1, y1, lv, 1])
        elif min(y1 - y0, x1 - x0) >= 2 and len(comp) == 2 * (x1 - x0 + y1 - y0) and \
                all(y in (y0, y1) or x in (x0, x1) for y, x in comp):
            out.append([x0, y0, x1, y1, lv, 0])
        else:
            return None
    return out


def process_files(srcs, cache, recorded=None):
    """The text of recorded frames (game/media/dmd/deff_NNN/fNNN.png of the effects in `recorded`, folder
    names; all of srcs when None), scanned in parallel and completed per effect, and the effects whose
    pictures (once their text is cleared) are only rectangles, boxes and blocks, drawn as such in HD:
    {src: (lines, rectangles, path of the frame with its letters and rectangles cleared, or None)}."""
    from PIL import Image
    scanned = [s for s in srcs if recorded is None or os.path.basename(os.path.dirname(s)) in recorded]
    jobs = [(s, cache) for s in scanned]
    if len(jobs) < 8:
        scans = [scan(j) for j in jobs]
    else:
        import multiprocessing
        with multiprocessing.Pool(os.cpu_count() or 2) as pool:
            scans = pool.map(scan, jobs, chunksize=2)
    found = dict(zip(scanned, scans))
    by_deff = {}
    for src in srcs:
        by_deff.setdefault(os.path.dirname(src), {})[src] = found.get(src, [])
    fonts = _cached_fonts()
    out = {}
    for folder, frames in by_deff.items():
        clear_dir = os.path.join(cache, "cleared", os.path.basename(folder))
        os.makedirs(clear_dir, exist_ok=True)
        done = complete_lines(frames, fonts)
        zoom = ZOOMS.get(os.path.basename(folder))
        if zoom:
            source = done.get(os.path.join(folder, zoom["source"]), ([], []))[0]
            for src in frames:
                z = zoom["zoom"].get(os.path.basename(src))
                if z is not None and source:
                    done[src] = ([line + [z, zoom["keep_left"]] for line in source] if z else [],
                                 [(y, x, None) for y in range(32) for x in range(zoom["keep_left"], 128)])
        pictures = {}
        for src, (lines, dots) in done.items():
            img = Image.open(src)
            a = levels(img)
            lit = [(y, x) for y, x, lv in dots if a[y][x] == lv or lv is None]
            for y, x in lit:
                a[y][x] = 0
            pictures[src] = (img, lit, a)
        rects = {src: shapes(a) for src, (_, _, a) in pictures.items()}
        if any(r is None for r in rects.values()) or not any(rects.values()):
            rects = {src: [] for src in rects}        # art: the picture stays
        for src, (img, lit, a) in pictures.items():
            lines = done[src][0]
            boxes = rects[src]
            for x0, y0, x1, y1, _, _ in boxes:
                lit += [(y, x) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)]
            if not lit:
                out[src] = (lines, boxes, None)
                continue
            dst = os.path.join(clear_dir, os.path.basename(src))
            clear_text(img, lit).save(dst)
            out[src] = (lines, boxes, dst)
    return out


def main():
    from PIL import Image
    fonts = load_fonts()
    for name in sys.argv[1:]:
        folder = os.path.join(GAME, "media", "dmd", name)
        for f in sorted(os.listdir(folder)):
            if f.endswith(".png"):
                lines = frame_text(Image.open(os.path.join(folder, f)), fonts)
                print(name, f, [(t, fid, x, b, lv, w) for t, fid, x, b, lv, w, _ in lines])
        folder_srcs = [os.path.join(folder, f) for f in sorted(os.listdir(folder)) if f.endswith(".png")]
        for src, (lines, boxes, _) in process_files(folder_srcs, os.path.join(ROOT, ".cache", "frame_text")).items():
            print("  completed", os.path.basename(src), lines, boxes)


if __name__ == "__main__":
    main()
