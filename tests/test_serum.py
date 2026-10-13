"""The Serum colourisation (serum/trn_174h.cRZ) read by scripts/serum.py: the file's layout, the frame CRC and
search of libserum, the colouring (dynamic zones, sprites), the nearest-frame match, and the effect frames
coloured from it (scripts/dmd_color.py serum_build)."""
import glob
import json
import os
import sys
import unittest
import zlib

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import dmd_color  # noqa: E402
import serum  # noqa: E402

GAME = os.path.join(ROOT, "game")
_serum = None


def load():
    global _serum
    if _serum is None:
        _serum = serum.Serum()
    return _serum


@unittest.skipUnless(os.path.exists(serum.CROM), "no Serum file")
class TestSerumFile(unittest.TestCase):
    def test_header(self):
        s = load()
        self.assertEqual(("trn_174h", 128, 32, 5368, 16, 64), (s.rom, s.width, s.height, s.nframes, s.nocolors,
                                                                  s.nccolors))
        self.assertEqual((54, 20, 0), (s.ncompmasks, s.nsprites, s.nbackgrounds))
        self.assertEqual(5368, sum(len(g["ids"]) for g in s.groups.values()))

    def test_crc_leaves_masked_dots_out(self):
        s = load()
        frame = bytes((x * 7 + y) % 16 for y in range(32) for x in range(128))
        self.assertEqual(zlib.crc32(frame), s.frame_hash(frame, 255, 0))
        mask = s.compmasks[6 * 4096:7 * 4096]
        kept = bytes(v for v, m in zip(frame, mask) if not m)
        self.assertEqual(zlib.crc32(kept), s.frame_hash(frame, 6, 0))
        self.assertEqual(zlib.crc32(bytes(min(1, v) for v in kept)), s.frame_hash(frame, 6, 1))
        # mask 6 hides the status panel (x < 41): a frame differing only there has the same CRC
        other = bytes(15 if i % 128 < 41 else v for i, v in enumerate(frame))
        self.assertEqual(s.frame_hash(frame, 6, 0), s.frame_hash(other, 6, 0))

    def test_unknown_frame_keeps_last_colours(self):
        s = load()
        s.reset()
        noise = bytes((i * 2654435761 >> 7) % 16 for i in range(4096))
        self.assertEqual((None, None, serum.NO_FRAME), s.colorize(noise))

    def test_sprite_size(self):
        s = load()
        for q in range(s.nsprites):
            w, h = s.sprite_sizes[q]
            self.assertTrue(0 <= w <= 128 and 0 <= h <= 128)


GENERATED = os.path.exists(os.path.join(GAME, "media", "dmd_color", "palettes.json"))


@unittest.skipUnless(os.path.exists(serum.CROM) and GENERATED, "no Serum file or media not generated")
class TestSerumFrames(unittest.TestCase):
    def frame(self, deff, name):
        from PIL import Image
        return Image.open(os.path.join(GAME, "media", "dmd", "deff_%03d" % deff, name))

    def test_known_frames(self):
        """The light cycle effect (deff 85) is in the colourisation frame for frame, its colour frames are the
        Serum v2 pictures (256x64 art) the export holds for them, black where HD draws its text."""
        from PIL import Image
        import serum_v2
        s = load()
        s.reset()
        frames = sorted(glob.glob(os.path.join(GAME, "media", "dmd", "deff_085", "f*.png")))
        ids = [s.identify(serum.shades(Image.open(p))) for p in frames]
        self.assertNotIn(serum.NO_FRAME, ids)
        index, z = serum_v2.load()
        e = index["deff_085/f040.png"]
        self.assertEqual(serum_v2.shades_key(serum.shades(Image.open(frames[40]))), e["sha"])
        want = serum_v2.picture(z, e)
        eff = json.load(open(os.path.join(GAME, "media", "dmd", "deff_085", "effect.json"), encoding="utf-8"))
        pics = [it["color_frames"] for it in eff["items"] if it["type"] == "frames"][0]
        got = Image.open(os.path.join(GAME, pics[40][len("res://"):])).convert("RGB")
        self.assertEqual((256, 64), got.size)
        w, g = want.load(), got.load()
        shown = [(x, y) for y in range(64) for x in range(256) if g[x, y] != (0, 0, 0)]
        self.assertGreater(len(shown), 4000)
        self.assertEqual([], [(x, y) for x, y in shown if g[x, y] != w[x, y]][:5])
        self.assertGreater(len(got.getcolors(1 << 16) or []), 200)      # HD art, not 64 colours

    def test_nearest_finds_the_art_under_the_text(self):
        """The shot award animation (deff 119) is in the colourisation only with its score drawn over it."""
        s = load()
        s.reset()
        sh = serum.shades(self.frame(119, "f001.png"))
        self.assertEqual(serum.NO_FRAME, s.identify(sh))
        fid, corr = s.nearest(sh)
        self.assertGreaterEqual(corr, serum.NEAR_MIN)
        self.assertTrue(3400 <= fid <= 3500, fid)
        fid, corr = s.nearest(serum.shades(self.frame(56, "f000.png")))     # Daft Punk: not in the file
        self.assertLess(corr, serum.NEAR_MIN)

    def test_capture_gives_the_screen(self):
        """Effects drawn from their bitmaps (text printed live) are in the colourisation only with their text:
        their emulator capture is, by CRC (Quorra, deff 62) or by screen when its values differ from the
        colourist's game (disc multiball, deff 47: JACKPOT=00), and colours them."""
        s = load()
        s.reset()
        self.assertEqual(serum.NO_FRAME, s.identify(serum.shades(self.frame(62, "f004.png"))))
        caps = dmd_color.capture_serum(s, dmd_color.capture_path(62))
        self.assertTrue(caps and all(by_crc and 5190 <= fid <= 5199 for _, fid, by_crc in caps))
        caps = dmd_color.capture_serum(s, dmd_color.capture_path(47))
        self.assertTrue(caps and all(not by_crc and 5136 <= fid <= 5160 for _, fid, by_crc in caps))
        self.assertEqual((serum.NO_FRAME, 1.0), s.fit(bytes(4096)))
        info = json.load(open(os.path.join(GAME, "media", "dmd_color", "palettes.json"), encoding="utf-8"))
        for deff in (47, 62, 90, 133):
            e = info["deffs"]["deff_%03d" % deff]
            self.assertEqual("serum", e["source"])
            self.assertEqual(e["capture_frames"], len(glob.glob(
                os.path.join(GAME, "media", "dmd", "deff_%03d" % deff, "f*.png"))))

    def test_palettes_json(self):
        info = json.load(open(os.path.join(GAME, "media", "dmd_color", "palettes.json"), encoding="utf-8"))
        self.assertEqual("trn_174h.cRZ", info["serum"])
        e = info["deffs"]["deff_085"]
        self.assertEqual(("serum", e["serum_frames"]), (e["source"], len(glob.glob(
            os.path.join(GAME, "media", "dmd", "deff_085", "f*.png")))))
        self.assertGreater(info["deffs"]["deff_119"]["near_frames"], 30)


class TestScale2x(unittest.TestCase):
    def test_libserum_upscale_keeps_lit_dots(self):
        """libserum's 2x (Scale2xPreserve): a corner is rounded as Scale2x does, except that a lit dot never takes
        a dark neighbour, so a one-dot diagonal stroke keeps every dot."""
        diag = [1, 0, 0, 0, 1, 0, 0, 0, 1]
        rows = dmd_color.scale2x_serum(diag, bytes(diag), 3, 3)
        self.assertEqual([[1, 1, 0, 0, 0, 0], [1, 1, 1, 0, 0, 0], [0, 1, 1, 1, 0, 0], [0, 0, 1, 1, 1, 0],
                          [0, 0, 0, 1, 1, 1], [0, 0, 0, 0, 1, 1]], rows)
        flat = dmd_color.scale2x_serum([5] * 9, bytes([1] * 9), 3, 3)
        self.assertEqual([[5] * 6] * 6, flat)


def _libserum():
    import serum_lib
    return serum_lib.library_path() if os.path.exists(serum.CROM) else None


@unittest.skipUnless(_libserum(), "libserum not built (scripts/serum_lib.py build, or TRON_LIBSERUM)")
class TestAgainstLibserum(unittest.TestCase):
    def test_same_colours_as_libserum(self):
        """scripts/serum.py colours every frame of the emulator captures as libserum itself does: same frame found,
        same colours (a dynamic colour past the 64 of a frame taken mod 64 by both)."""
        from PIL import Image, ImageSequence
        import serum_lib
        py, ls = serum.Serum(), serum_lib.LibSerum()
        self.addCleanup(ls.close)
        n = 0
        for g in sorted(glob.glob(os.path.join(ROOT, "assets", "mpf_package", "media", "dmd", "deff_*",
                                               "reference_capture.gif")))[::3]:
            for fr in ImageSequence.Iterator(Image.open(g)):
                sh = serum.shades(fr.convert("RGB"))
                a, pa, fa = py.colorize(sh)
                b, pb, fb = ls.colorize(sh)
                self.assertEqual(None if fa == serum.NO_FRAME else fa, fb, g)
                if a is not None:
                    self.assertEqual([pa[v] for v in a], [pb[v % 64] for v in b], g)
                n += 1
        self.assertGreater(n, 2000)


class TestV2Export(unittest.TestCase):
    """serum/trn_174h_v2.zip: the Serum v2 colourisation's 256x64 frames (scripts/serum_v2.py export)."""

    def test_export(self):
        import serum_v2
        from PIL import Image
        index, z = serum_v2.load()
        self.assertGreater(len(index), 7000)
        caps = [k for k in index if "/cap" in k]
        self.assertGreater(len(caps), 5000)
        e = index["deff_119/f000.png"]               # the shot award: v1 knew it only under its text
        self.assertEqual(serum_v2.shades_key(serum.shades(Image.open(os.path.join(
            GAME, "media", "dmd", "deff_119", "f000.png")))), e["sha"])
        self.assertEqual((256, 64), serum_v2.picture(z, e).size)

    def test_build_uses_it(self):
        """The colour build takes the v2 pictures for most frames (palettes.json v2_frames)."""
        info = json.load(open(os.path.join(GAME, "media", "dmd_color", "palettes.json"), encoding="utf-8"))
        v2 = sum(e.get("v2_frames", 0) for e in info["deffs"].values() if isinstance(e, dict))
        self.assertGreater(v2, 2000)


@unittest.skipUnless(_libserum() and os.path.exists(os.path.join(ROOT, "serum", "trn_174h.cROMc")),
                     "libserum not built (scripts/serum_lib.py build, or TRON_LIBSERUM)")
class TestV2AgainstLibserum(unittest.TestCase):
    def test_export_is_libserums(self):
        """The export's pictures are what libserum gives for the effect's frames from a fresh load."""
        from PIL import Image
        import serum_lib
        import serum_v2
        index, z = serum_v2.load()
        ls = serum_lib.LibSerum(serum_lib.CROMC, flags=3)
        self.addCleanup(ls.close)
        for p in sorted(glob.glob(os.path.join(GAME, "media", "dmd", "deff_063", "f*.png"))):
            fid, _, rgb = ls.colorize_v2(serum.shades(Image.open(p)))
            e = index["deff_063/" + os.path.basename(p)]
            self.assertEqual(e["id"], fid)
            self.assertEqual(serum_v2.picture(z, e).tobytes(), rgb)


if __name__ == "__main__":
    unittest.main()
