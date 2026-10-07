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


GENERATED = os.path.exists(os.path.join(GAME, "media", "dmd_hd_color", "palettes.json"))


@unittest.skipUnless(os.path.exists(serum.CROM) and GENERATED, "no Serum file or media not generated")
class TestSerumFrames(unittest.TestCase):
    def frame(self, deff, name):
        from PIL import Image
        return Image.open(os.path.join(GAME, "media", "dmd", "deff_%03d" % deff, name))

    def test_known_frames(self):
        """The light cycle effect (deff 85) is in the colourisation frame for frame, the colour frames are its."""
        from PIL import Image
        s = load()
        s.reset()
        frames = sorted(glob.glob(os.path.join(GAME, "media", "dmd", "deff_085", "f*.png")))
        ids = [s.identify(serum.shades(Image.open(p))) for p in frames]
        self.assertNotIn(serum.NO_FRAME, ids)
        s.reset()
        sh = serum.shades(Image.open(frames[40]))
        idx, pal, fid = s.colorize(sh)
        want = dmd_color.rgb_image(dmd_color.scale_indices(idx, 128, 32, dmd_color.COLOR_SCALE), pal)
        got = Image.open(frames[40].replace(os.sep + "dmd" + os.sep, os.sep + "dmd_hd_color" + os.sep))
        self.assertEqual(want.tobytes(), got.convert("RGB").tobytes())
        self.assertGreater(len(got.getcolors(4096) or []), 8)          # Serum colours, not a 16-shade ramp

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
        info = json.load(open(os.path.join(GAME, "media", "dmd_hd_color", "palettes.json"), encoding="utf-8"))
        for deff in (47, 62, 90, 133):
            e = info["deffs"]["deff_%03d" % deff]
            self.assertEqual("serum", e["source"])
            self.assertEqual(e["capture_frames"], len(glob.glob(
                os.path.join(GAME, "media", "dmd", "deff_%03d" % deff, "f*.png"))))

    def test_palettes_json(self):
        info = json.load(open(os.path.join(GAME, "media", "dmd_hd_color", "palettes.json"), encoding="utf-8"))
        self.assertEqual("trn_174h.cRZ", info["serum"])
        e = info["deffs"]["deff_085"]
        self.assertEqual(("serum", e["serum_frames"]), (e["source"], len(glob.glob(
            os.path.join(GAME, "media", "dmd", "deff_085", "f*.png")))))
        self.assertGreater(info["deffs"]["deff_119"]["near_frames"], 30)


if __name__ == "__main__":
    unittest.main()
