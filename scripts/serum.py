#!/usr/bin/env python3
"""Serum colourisation (the colour DMD format of libserum / PinMAME / DMDExt) read and applied in Python.

The Tron Legacy LE colourisation, serum/trn_174h.cRZ (a zip holding trn_174h.cRom), is a Serum v1 file:
5368 coloured frames of the ROM's 128x32 display. Each one is found by a CRC32 of the 16-shade frame the
ROM draws (optionally with a comparison mask: masked dots left out, and a "shape" mode: every lit dot
counts as 1), and gives the frame in colour as indices into its own 64-colour palette. Inside its dynamic
zones a dot's colour depends on its shade instead (dyna4cols: 16 sets of 16 colours per frame), so text
and scores drawn over an animation are coloured too. Sprites (small pictures the ROM moves around) are
found by a detection dword and a detection area of their dots, and drawn over the frame in their colours.
Colour rotations (colour cycling) are recorded but not applied: the frames here are still pictures.

This is a port of libserum's v1 loader and colouriser (Serum_LoadFile, Identify_Frame, Colorize_Frame,
Check_Sprites, Colorize_Sprite): the same layout, CRC and search order, so a frame gets the colours it
gets in PinMAME. As in libserum, a frame the file does not know keeps the colours of the last frame found.

    .venv/bin/python scripts/serum.py info [CROM]            # the header and counts
    .venv/bin/python scripts/serum.py export OUTDIR [CROM]   # every asset of the file as PNG + JSON
    .venv/bin/python scripts/serum.py color IN.png OUT.png [CROM]   # one classic frame coloured (128x32)
"""
import json
import operator
import os
import struct
import sys
import zipfile
import zlib

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CROM = os.path.join(ROOT, "serum", "trn_174h.cRZ")

MAX_DYNA_SETS = 16          # MAX_DYNA_4COLS_PER_FRAME
MAX_SPRITE_SIZE = 128
MAX_SPRITES_PER_FRAME = 32
MAX_COLOR_ROTATIONS = 8
MAX_SPRITE_DETECT_AREAS = 4
NO_FRAME = -1
NEAR_X = 42                 # the status panel: left of this column in most frames (Serum mask 6 leaves it out)
NEAR_MIN = 0.75             # nearest(): from this correlation on, the same art (deffs 116-124: 0.75-0.97; others < 0.6)
# fit(): a frame the file does not know by its CRC (the ROM's text at other places: values of other lengths) is
# the same screen as a Serum frame when its lit dots disagree on at most FIT_MAX of the dots that frame compares
# outside its dynamic zones, with FIT_RECALL of that frame's lit dots lit. Frames that compare few dots, few lit
# ones, or mostly lit ones (borders, flashes) match too much and are left out.
FIT_MAX = 0.08
FIT_RECALL = 0.85
FIT_MIN_KNOWN = 300
FIT_MIN_LIT = 40
FIT_MAX_LIT = 0.5


class Serum:
    def __init__(self, path=CROM):
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as z:
                name = next(n for n in z.namelist() if n.lower().endswith(".crom"))
                data = z.read(name)
        else:
            with open(path, "rb") as f:
                data = f.read()
        self.path = path
        self.rom = data[:64].split(b"\0")[0].decode("latin-1")
        pos = 64
        (sizeheader,) = struct.unpack_from("<I", data, pos)
        if sizeheader >= 14 * 4:
            raise ValueError("Serum v2 (cROMc) files are not supported")
        (self.width, self.height, self.nframes, self.nocolors, self.nccolors, self.ncompmasks, self.nmovmasks,
         self.nsprites) = struct.unpack_from("<8I", data, pos + 4)
        pos += 36
        self.nbackgrounds = 0
        if sizeheader >= 13 * 4:
            (self.nbackgrounds,) = struct.unpack_from("<H", data, pos)
            pos += 2
        self.version = sizeheader
        n, px = self.nframes, self.width * self.height

        def take(size):
            nonlocal pos
            chunk = data[pos:pos + size]
            if len(chunk) != size:
                raise ValueError("truncated Serum file")
            pos += size
            return chunk

        def words(fmt, count):
            return list(struct.unpack("<%d%s" % (count, fmt), take(count * struct.calcsize(fmt))))

        self.hashcodes = words("I", n)
        self.shapecompmode = take(n)
        self.compmaskID = take(n)
        self.movrctID = take(n)
        self.compmasks = take(self.ncompmasks * px)
        self.movrcts = take(self.nmovmasks * px)
        self.cpal = take(n * 3 * self.nccolors)
        self.cframes = take(n * px)
        self.dynamasks = take(n * px)
        self.dyna4cols = take(n * MAX_DYNA_SETS * self.nocolors)
        self.framesprites = take(n * MAX_SPRITES_PER_FRAME)
        pairs = take(self.nsprites * MAX_SPRITE_SIZE * MAX_SPRITE_SIZE * 2)
        self.spritec, self.spriteo = pairs[0::2], pairs[1::2]      # colour index, original shade (255 = none)
        self.activeframes = take(n)
        self.colorrotations = take(n * 3 * MAX_COLOR_ROTATIONS)
        self.spritedetdwords = words("I", self.nsprites * MAX_SPRITE_DETECT_AREAS)
        self.spritedetdwordpos = words("H", self.nsprites * MAX_SPRITE_DETECT_AREAS)
        self.spritedetareas = words("H", self.nsprites * 4 * MAX_SPRITE_DETECT_AREAS)
        self.triggerIDs = words("I", n) if sizeheader >= 11 * 4 else [0xFFFFFFFF] * n
        self.framespriteBB = (words("H", n * MAX_SPRITES_PER_FRAME * 4) if sizeheader >= 12 * 4 else
                              [0, 0, self.width - 1, self.height - 1] * (n * MAX_SPRITES_PER_FRAME))
        if sizeheader >= 13 * 4:
            self.backgroundframes = take(self.nbackgrounds * px)
            self.backgroundIDs = words("H", n)
            self.backgroundBB = words("H", n * 4)
        else:
            self.backgroundframes, self.backgroundIDs, self.backgroundBB = b"", [0xFFFF] * n, [0] * (4 * n)
        if pos != len(data):
            raise ValueError("Serum file: %d bytes left after the last table" % (len(data) - pos))
        # identification: frames grouped by (comparison mask, shape mode), as Identify_Frame compares them
        self.groups = {}
        for i in range(n):
            g = self.groups.setdefault((self.compmaskID[i], self.shapecompmode[i]), {"ids": [], "hash": {}})
            g["ids"].append(i)
            g["hash"].setdefault(self.hashcodes[i], []).append(i)
        self._mask_lut = {}
        self.sprite_sizes = [self._sprite_size(s) for s in range(self.nsprites)]
        self.reset()

    # ------------------------------------------------------------------ state (libserum keeps the last frame)

    def reset(self):
        self.lastfound = 0
        self.last_frame = None      # colour indices of the last coloured frame
        self.last_id = NO_FRAME

    # ------------------------------------------------------------------ identification

    def frame_hash(self, frame, mask, shape):
        """crc32_fast / crc32_fast_mask: CRC32 of the shades, the masked dots left out, lit dots as 1 in shape
        mode."""
        if mask < 255:
            if mask not in self._mask_lut:
                m = self.compmasks[mask * self.width * self.height:(mask + 1) * self.width * self.height]
                keep = [k for k, v in enumerate(m) if not v]
                self._mask_lut[mask] = (operator.itemgetter(*keep) if len(keep) > 1 else
                                        lambda f, keep=keep: tuple(f[k] for k in keep))
            frame = bytes(self._mask_lut[mask](frame))
        if shape:
            frame = frame.translate(bytes([0] + [1] * 255))
        return zlib.crc32(frame)

    def identify(self, frame):
        """The id of the frame (bytes of shades 0..15, 128x32) as Identify_Frame finds it: the groups taken
        in the order of their first frame from the last one found, the first matching frame of a group
        from there; NO_FRAME if none."""
        n, last = self.nframes, self.lastfound
        best = None
        for key, g in self.groups.items():
            first = min((i - last) % n for i in g["ids"])
            if best is not None and first >= best[0]:
                continue
            hits = g["hash"].get(self.frame_hash(frame, *key))
            if hits:
                best = (first, min(hits, key=lambda i: (i - last) % n))
        if best is None:
            return NO_FRAME
        self.lastfound = best[1]
        return best[1]

    # ------------------------------------------------------------------ colouring

    def palette(self, fid):
        """The 64 (r, g, b) colours of a frame."""
        p = self.cpal[fid * 3 * self.nccolors:(fid + 1) * 3 * self.nccolors]
        return [tuple(p[3 * k:3 * k + 3]) for k in range(self.nccolors)]

    def colorize_frame(self, frame, fid):
        """Colorize_Frame: colour indices of the frame (background, dynamic zones by shade, else cframes)."""
        w, h, px = self.width, self.height, self.width * self.height
        cf = self.cframes[fid * px:(fid + 1) * px]
        dm = self.dynamasks[fid * px:(fid + 1) * px]
        d4 = self.dyna4cols[fid * MAX_DYNA_SETS * self.nocolors:(fid + 1) * MAX_DYNA_SETS * self.nocolors]
        out = bytearray(cf)
        for k in range(px):
            layer = dm[k]
            if layer != 255:
                # 3 frames of the Tron file have a dynamic set of colours 128-143, past the 64 of a frame:
                # taken as 0-15 (libserum would read past the palette)
                out[k] = d4[layer * self.nocolors + frame[k]] % self.nccolors
        bg = self.backgroundIDs[fid]
        if bg < self.nbackgrounds:
            x0, y0, x1, y1 = self.backgroundBB[4 * fid:4 * fid + 4]
            bgf = self.backgroundframes[bg * px:(bg + 1) * px]
            for y in range(y0, min(y1, h - 1) + 1):
                for x in range(x0, min(x1, w - 1) + 1):
                    if frame[y * w + x] == 0:
                        out[y * w + x] = bgf[y * w + x]
        return out

    def _sprite_size(self, s):
        base, wid, hei = s * MAX_SPRITE_SIZE * MAX_SPRITE_SIZE, 0, 0
        for y in range(MAX_SPRITE_SIZE):
            row = self.spriteo[base + y * MAX_SPRITE_SIZE:base + (y + 1) * MAX_SPRITE_SIZE]
            xs = [x for x, v in enumerate(row) if v < 255]
            if xs:
                wid, hei = max(wid, xs[-1] + 1), y + 1
        return wid, hei

    def find_sprites(self, frame, fid):
        """Check_Sprites: [(sprite, frame x, frame y, sprite x, sprite y, width, height), ...] in the frame."""
        w, S = self.width, MAX_SPRITE_SIZE
        found = []
        for slot in range(MAX_SPRITES_PER_FRAME):
            q = self.framesprites[fid * MAX_SPRITES_PER_FRAME + slot]
            if q == 255:
                break
            spw, sph = self.sprite_sizes[q]
            bb = (fid * MAX_SPRITES_PER_FRAME + slot) * 4
            minx, miny, maxx, maxy = self.framespriteBB[bb:bb + 4]
            for tm in range(MAX_SPRITE_DETECT_AREAS):
                a = (q * MAX_SPRITE_DETECT_AREAS + tm) * 4
                if self.spritedetareas[a] == 0xFFFF:
                    continue
                detx, dety, detw, deth = self.spritedetareas[a:a + 4]
                dword = self.spritedetdwords[q * MAX_SPRITE_DETECT_AREAS + tm]
                sddp = self.spritedetdwordpos[q * MAX_SPRITE_DETECT_AREAS + tm]
                sprx, spry = sddp % S, sddp // S
                for ty in range(miny, maxy + 1):
                    for tx in range(minx, maxx - 2):
                        j = ty * w + tx
                        if frame[j] | frame[j + 1] << 8 | frame[j + 2] << 16 | frame[j + 3] << 24 != dword:
                            continue
                        if tx - minx < sprx - detx or ty - miny < spry - dety:
                            continue
                        offx, offy = tx - sprx + detx, ty - spry + dety
                        if offx + detw > maxx + 1 or offy + deth > maxy + 1:
                            continue
                        base = q * S * S
                        there = all(
                            v == 255 or v == frame[(tk + offy) * w + tl + offx]
                            for tk in range(deth) for tl in range(detw)
                            for v in (self.spriteo[base + (tk + dety) * S + tl + detx],))
                        if not there:
                            continue
                        if tx - minx < sprx:
                            spx, frx = sprx - (tx - minx), minx
                            wid = min(spw - spx, maxx - minx + 1)
                        else:
                            spx, frx = 0, tx - sprx
                            wid = min(spw, maxx - frx + 1)
                        if ty - miny < spry:
                            spy, fry = spry - (ty - miny), miny
                            hei = min(sph - spy, maxy - miny + 1)
                        else:
                            spy, fry = 0, ty - spry
                            hei = min(sph, maxy - fry + 1)
                        hit = (q, frx, fry, spx, spy, wid, hei)
                        if hit not in found:
                            found.append(hit)
        return found

    def draw_sprite(self, out, hit):
        q, frx, fry, spx, spy, wid, hei = hit
        S, w = MAX_SPRITE_SIZE, self.width
        for tj in range(hei):
            for ti in range(wid):
                k = (q * S + tj + spy) * S + ti + spx
                if self.spriteo[k] < 255 and 0 <= fry + tj < self.height and 0 <= frx + ti < w:
                    out[(fry + tj) * w + frx + ti] = self.spritec[k]

    def colorize(self, frame):
        """(colour indices, palette, frame id or NO_FRAME) for a frame of shades, keeping libserum's state:
        a frame not found (or found but inactive) keeps the last colours; None before any is found."""
        fid = self.identify(frame)
        if fid != NO_FRAME and self.activeframes[fid]:
            out = self.colorize_frame(frame, fid)
            for hit in self.find_sprites(frame, fid):
                self.draw_sprite(out, hit)
            self.last_frame, self.last_id = out, fid
            return out, self.palette(fid), fid
        if self.last_frame is None:
            return None, None, NO_FRAME
        return self.last_frame, self.palette(self.last_id), NO_FRAME

    # ------------------------------------------------------------------ nearest frame (not in libserum)

    def nearest(self, frame, x0=NEAR_X):
        """(id, correlation) of the Serum frame that looks most like a frame it does not know (the same art
        with the ROM's text left out, say): right of x0 (the status panel), the frame's shades against each
        Serum frame's luminance at half size, by Pearson correlation (1 = same picture; NEAR_MIN and up:
        the same art)."""
        from PIL import Image, ImageChops, ImageStat
        if not hasattr(self, "_near"):
            self._near = []
            for i in range(self.nframes):
                lut = bytes(min(255, round(0.3 * r + 0.59 * g + 0.11 * b)) for r, g, b in self.palette(i)) \
                    + bytes(256 - self.nccolors)
                lum = self.cframes[i * self.width * self.height:(i + 1) * self.width * self.height].translate(lut)
                img = self._near_key(Image.frombytes("L", (self.width, self.height), lum), x0)
                st = ImageStat.Stat(img)
                self._near.append((img, st.mean[0], st.stddev[0]))
        q = self._near_key(Image.frombytes("L", (self.width, self.height), bytes(v * 17 for v in frame)), x0)
        st = ImageStat.Stat(q)
        qm, qs = st.mean[0], st.stddev[0]
        if qs < 1:
            return NO_FRAME, 0.0
        best = (-2.0, NO_FRAME)
        for i, (img, m, sd) in enumerate(self._near):
            if sd < 1:
                continue
            exy = ImageStat.Stat(ImageChops.multiply(q, img)).mean[0] * 255
            best = max(best, ((exy - qm * m) / (qs * sd), i))
        return best[1], best[0]

    def fit(self, frame):
        """(id, share of disagreeing dots) of the Serum frame whose screen the frame (shades 0..15) shows when
        its CRC does not find it, or (NO_FRAME, 1.0): per Serum frame, the dots it compares (outside its
        comparison mask) and colours by itself (outside its dynamic zones) are lit or dark as its colours
        say; the frame must agree on all but FIT_MAX of them, its lit dots FIT_RECALL lit (see FIT_MAX)."""
        if not hasattr(self, "_fit"):
            self._fit = []
            px = self.width * self.height
            for i in range(self.nframes):
                lit_c = [0.3 * r + 0.59 * g + 0.11 * b > 20 for r, g, b in self.palette(i)]
                m = self.compmaskID[i]
                comp = self.compmasks[m * px:(m + 1) * px] if m < 255 else bytes(px)
                cf, dm = self.cframes[i * px:(i + 1) * px], self.dynamasks[i * px:(i + 1) * px]
                known = int("".join("1" if not comp[k] and dm[k] == 255 else "0" for k in range(px)), 2)
                lit = known & int("".join("1" if lit_c[cf[k] % self.nccolors] else "0" for k in range(px)), 2)
                nk, nl = known.bit_count(), lit.bit_count()
                if nk >= FIT_MIN_KNOWN and FIT_MIN_LIT <= nl <= FIT_MAX_LIT * nk:
                    self._fit.append((i, known, lit, nk, nl))
        q = int("".join("1" if v else "0" for v in frame), 2)
        best = (1.0, NO_FRAME)
        for i, known, lit, nk, nl in self._fit:
            miss = ((lit & ~q) | (known & ~lit & q)).bit_count() / nk
            if miss <= FIT_MAX and miss < best[0] and (lit & q).bit_count() >= FIT_RECALL * nl:
                best = (miss, i)
        return best[1], best[0]

    def _near_key(self, img, x0):
        from PIL import Image
        img = img.crop((x0, 0, self.width, self.height))
        return img.resize((img.width // 2, img.height // 2), Image.BOX)

    def rotations(self, fid):
        """The colour rotations of a frame: [(first colour, count, delay in 10 ms), ...]."""
        r = self.colorrotations[fid * 3 * MAX_COLOR_ROTATIONS:(fid + 1) * 3 * MAX_COLOR_ROTATIONS]
        return [tuple(r[3 * k:3 * k + 3]) for k in range(MAX_COLOR_ROTATIONS) if r[3 * k] != 255 and r[3 * k + 1]]


def shades(img):
    """A classic frame (PIL image: the 16 shades as greys 0, 17, .. 255) -> bytes of shades 0..15."""
    import dmd_hd
    return bytes(min(15, round(v / 17)) for v in dmd_hd.grey(img).tobytes())


def to_image(indices, pal, w=128, h=32):
    from PIL import Image
    img = Image.new("RGB", (w, h))
    img.putdata([pal[v] for v in indices])
    return img


# ---------------------------------------------------------------------- export of the whole file

def export(out, path=CROM):
    """Every asset of the file: frames/NNNN.png (each frame in its colours; the dynamic zones, where the ROM's
    text and scores take colours by shade, as with no text: shade 0), sheets/ (256 frames each, numbered),
    palettes.json, sprites/, masks/ (the comparison masks), frames.json (per frame: CRC, mask, dynamic
    colour sets, sprites, colour rotations, PuP trigger)."""
    from PIL import Image, ImageDraw
    s = Serum(path)
    px = s.width * s.height
    for d in ("frames", "sheets", "sprites", "masks"):
        os.makedirs(os.path.join(out, d), exist_ok=True)
    meta, blank = [], [0] * px
    for i in range(s.nframes):
        img = to_image(s.colorize_frame(bytes(blank), i), s.palette(i), s.width, s.height)
        img.save(os.path.join(out, "frames", "%04d.png" % i))
        dyn = sorted(set(s.dynamasks[i * px:(i + 1) * px]) - {255})
        meta.append({"id": i, "hash": "%08x" % s.hashcodes[i], "mask": None if s.compmaskID[i] == 255 else
                     s.compmaskID[i], "shape": s.shapecompmode[i], "active": s.activeframes[i],
                     "dynamic_sets": dyn, "sprites": [v for v in s.framesprites[i * 32:(i + 1) * 32] if v < 255],
                     "rotations": s.rotations(i), "trigger": None if s.triggerIDs[i] == 0xFFFFFFFF else s.triggerIDs[i]})
    for b in range(0, s.nframes, 256):
        sheet = Image.new("RGB", (16 * (s.width + 2), 16 * (s.height + 10)), (40, 40, 40))
        draw = ImageDraw.Draw(sheet)
        for i in range(b, min(b + 256, s.nframes)):
            x, y = (i - b) % 16 * (s.width + 2), (i - b) // 16 * (s.height + 10)
            sheet.paste(Image.open(os.path.join(out, "frames", "%04d.png" % i)), (x + 1, y + 9))
            draw.text((x + 2, y), str(i), fill=(200, 200, 200))
        sheet.save(os.path.join(out, "sheets", "frames_%04d-%04d.png" % (b, min(b + 255, s.nframes - 1))))
    for q in range(s.nsprites):
        w, h = s.sprite_sizes[q]
        img = Image.new("RGBA", (max(1, w), max(1, h)))
        pal = None
        for i in range(s.nframes):            # a frame that shows the sprite gives its palette
            if q in s.framesprites[i * 32:(i + 1) * 32]:
                pal = s.palette(i)
                break
        pal = pal or [(v * 4, v * 4, v * 4) for v in range(64)]
        img.putdata([pal[s.spritec[(q * 128 + y) * 128 + x]] + (255,) if s.spriteo[(q * 128 + y) * 128 + x] < 255
                     else (0, 0, 0, 0) for y in range(max(1, h)) for x in range(max(1, w))])
        img.save(os.path.join(out, "sprites", "sprite_%02d.png" % q))
    for m in range(s.ncompmasks):
        Image.frombytes("L", (s.width, s.height),
                        bytes(255 if v else 0 for v in s.compmasks[m * px:(m + 1) * px])).save(
            os.path.join(out, "masks", "compmask_%02d.png" % m))
    with open(os.path.join(out, "palettes.json"), "w", encoding="utf-8") as f:
        json.dump({str(i): ["#%02x%02x%02x" % c for c in s.palette(i)] for i in range(s.nframes)}, f, indent=0)
    with open(os.path.join(out, "frames.json"), "w", encoding="utf-8") as f:
        json.dump({"rom": s.rom, "width": s.width, "height": s.height, "frames": s.nframes,
                   "original_shades": s.nocolors, "colors_per_frame": s.nccolors, "compmasks": s.ncompmasks,
                   "sprites": s.nsprites, "backgrounds": s.nbackgrounds, "frame_info": meta}, f, indent=0)
    return s.nframes


def main(argv):
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    if not argv or argv[0] not in ("info", "export", "color"):
        print(__doc__)
        return 2
    if argv[0] == "info":
        s = Serum(argv[1] if len(argv) > 1 else CROM)
        print("rom %s  %dx%d  frames %d  shades %d  colours/frame %d  masks %d  sprites %d  backgrounds %d  "
              "groups %d" % (s.rom, s.width, s.height, s.nframes, s.nocolors, s.nccolors, s.ncompmasks,
                             s.nsprites, s.nbackgrounds, len(s.groups)))
        return 0
    if argv[0] == "export":
        print("%d frames exported to %s" % (export(argv[1], argv[2] if len(argv) > 2 else CROM), argv[1]))
        return 0
    from PIL import Image
    s = Serum(argv[3] if len(argv) > 3 else CROM)
    idx, pal, fid = s.colorize(shades(Image.open(argv[1])))
    if idx is None:
        print("frame not in the colourisation")
        return 1
    to_image(idx, pal).save(argv[2])
    print("frame %d" % fid)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
