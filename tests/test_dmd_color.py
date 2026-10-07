"""The HD colour DMD: the colour map (game/tools/dmd_colormap.json, scripts/pup_colormap.py), the palettes and
the colour upscaler (scripts/dmd_color.py), the generated colour frames (scripts/gen_media.py
build_color_frames), the run.py switch, and in Godot (game/tools/dmd_mode.gd): --dmd-color=off gives the grey
HD frames as before colour existed, colour leaves classic mode alone."""
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import dmd_color  # noqa: E402
import dmd_hd  # noqa: E402
import run  # noqa: E402
import toolchain as tc  # noqa: E402
from tests import test_dmd_hd  # noqa: E402

GAME = os.path.join(ROOT, "game")
DATA = os.path.join(GAME, "tron", "media_data.json")


def image(rows):
    from PIL import Image
    img = Image.new("L", (len(rows[0]), len(rows)))
    img.putdata([v for row in rows for v in row])
    return img


class TestColormap(unittest.TestCase):
    def setUp(self):
        self.cmap = dmd_color.load_colormap()

    def test_palettes(self):
        for entry in [self.cmap["default"], self.cmap["text"]] + list(self.cmap["deffs"].values()):
            for hue in entry["hues"]:
                self.assertIn(hue if isinstance(hue, str) else "number", list(dmd_color.HUES) + ["number"])
        pal = dmd_color.palette(2, self.cmap)                       # no PuP video: the default (cyan)
        self.assertEqual(16, len(pal))
        self.assertEqual((0, 0, 0), pal[0])
        r, g, b = pal[7]
        self.assertTrue(b > r and g > r, pal[7])                     # cyan
        self.assertTrue(min(pal[15]) > 200, pal[15])                 # the white highlight
        lum = [sum(c) for c in pal]
        self.assertEqual(lum, sorted(lum))                           # brighter shade, brighter colour
        r, g, b = dmd_color.text_palette(self.cmap)[15]
        self.assertTrue(b > 200 and b > 1.5 * r and b > g, (r, g, b))   # text: blue

    def test_pup_matches(self):
        """The PuP-Pack's captures name their effects: the effects with their own video, and those that
        share their feature's, have hues; CLU and the light cycles are warm (orange), the Portal cool."""
        deffs = self.cmap["deffs"]
        own = [d for d, e in deffs.items() if "via" not in e]
        self.assertGreaterEqual(len(own), 60)
        self.assertGreaterEqual(len(deffs), 90)
        for d, e in deffs.items():
            self.assertTrue(e["videos"], d)
            if "via" in e:
                self.assertIn(str(e["via"]), deffs)
        for d in (71, 85, 87):
            self.assertIn(deffs[str(d)]["hues"][0], ("orange", "red"), d)
        self.assertIn(deffs["140"]["hues"][0], ("cyan", "blue"))
        self.assertIn(deffs["108"]["hues"][0], ("red", "orange"))     # the Recognizer

    def test_only_film_colours(self):
        """Blue, cyan, red / red-orange, white and black only: no green, violet or yellow anywhere (Vincent)."""
        import colorsys
        for d, e in self.cmap["deffs"].items():
            self.assertTrue(set(e["hues"]) <= set(dmd_color.HUES), (d, e["hues"]))
        for d in self.cmap["deffs"]:
            for rgb in dmd_color.palette(int(d), self.cmap):
                h, s, v = colorsys.rgb_to_hsv(*[c / 255 for c in rgb[:3]])
                if s > 0.25 and v > 0.15:
                    deg = h * 360
                    self.assertTrue(deg < 30 or deg > 340 or 180 <= deg <= 240, (d, rgb, deg))

    def test_colormap_is_small(self):
        self.assertLess(os.path.getsize(dmd_color.COLORMAP), 64 * 1024)


class TestColorUpscale(unittest.TestCase):
    def test_scale2x(self):
        self.assertEqual([[5, 5], [5, 5]], dmd_color.scale2x([[5]]))
        flat = [[1, 1, 1], [1, 1, 1]]
        self.assertEqual([[1] * 6] * 4, dmd_color.scale2x(flat))
        diag = [[0, 0, 0], [0, 9, 9], [0, 9, 9]]                       # a corner: rounded one step finer
        big = dmd_color.scale2x(diag)
        self.assertEqual(0, big[2][2])                                  # the outer half of the corner dot
        self.assertEqual(9, big[3][3])
        line = [[0, 0, 0], [7, 7, 7], [0, 0, 0]]                       # a one-dot line stays two pixels wide
        self.assertEqual([0, 0, 7, 7, 0, 0], [r[3] for r in dmd_color.scale2x(line)])

    def test_colour_2x(self):
        rows = [[0] * 16 for _ in range(10)]
        for y in range(2, 8):
            for x in range(2, 14):
                rows[y][x] = 255 if x >= 8 else 68
        pal = dmd_color.ramp("orange", "cyan")
        out = dmd_color.upscale_color_2x(image(rows), pal)
        self.assertEqual((32, 20), out.size)
        self.assertEqual(pal[4], out.getpixel((8, 10)))
        self.assertEqual(pal[15], out.getpixel((22, 10)))
        self.assertLessEqual(len(out.getcolors(64)), 3)                 # flat colours: crisp, no blur
        text = bytes(255 if x >= 8 and 2 <= y < 8 else 0 for y in range(10) for x in range(16))
        tpal = dmd_color.text_palette()
        out = dmd_color.upscale_color_2x(image(rows), pal, tpal, text)
        self.assertEqual(tpal[15], out.getpixel((22, 10)))
        self.assertEqual(pal[4], out.getpixel((8, 10)))

    def test_grey_palette_gives_the_grey_frame(self):
        """With a palette of greys the colour upscale is the HD grey frame, to edge rounding."""
        from PIL import ImageChops
        rows = [[0] * 16 for _ in range(10)]
        for y in range(2, 8):
            for x in range(2, 14):
                rows[y][x] = 255 if 5 <= x <= 9 else 68
        grey = image(rows)
        out = dmd_color.upscale_color(grey, [(k * 17,) * 3 for k in range(16)], 8)
        ref = dmd_hd.upscale_levels(grey, 8)
        diff = ImageChops.difference(out.convert("L"), ref)
        self.assertEqual(out.size, ref.size)
        self.assertLessEqual(diff.getextrema()[1], 40)
        self.assertLess(sum(1 for p in diff.tobytes() if p > 2), 0.03 * len(diff.tobytes()))

    def test_shades_take_their_colours(self):
        rows = [[0] * 16 for _ in range(10)]
        for y in range(2, 8):
            for x in range(2, 14):
                rows[y][x] = 255 if x >= 8 else 68           # shade 15 and shade 4
        pal = dmd_color.ramp("orange", "cyan")
        out = dmd_color.upscale_color(image(rows), pal, 8)
        self.assertEqual(pal[4], out.getpixel((4 * 8, 5 * 8)))
        self.assertEqual(pal[15], out.getpixel((11 * 8, 5 * 8)))
        self.assertEqual((0, 0, 0), out.getpixel((2, 2)))

    def test_text_dots(self):
        rows = [[0] * 128 for _ in range(32)]
        for x in range(50, 60):
            rows[10][x] = 255                                # a line of shade 15: a flat frame (text screen)
        flat = image(rows)
        self.assertEqual(10, sum(1 for p in dmd_color.frame_text_dots({"lines": [], "panel": False}, flat) if p))
        for x in range(50, 100):
            rows[20][x] = 68                                 # art in another shade: not flat
        art = image(rows)
        self.assertIsNone(dmd_color.frame_text_dots({"lines": [], "panel": False}, art))
        fg = [i // 128 == 10 and 50 <= i % 128 < 60 for i in range(4096)]
        bg = [i // 128 == 11 and 50 <= i % 128 < 60 for i in range(4096)]
        dots = dmd_color.frame_text_dots({"lines": [(fg, bg)], "panel": False}, art)
        self.assertEqual(10, sum(1 for p in dots if p))      # the line's dots only
        rows[11][55] = 255
        rows[11][56] = 255
        rows[11][57] = 255                                   # its cell not dark: not the text
        self.assertIsNone(dmd_color.frame_text_dots({"lines": [(fg, bg)], "panel": False}, image(rows)))


GENERATED = os.path.exists(os.path.join(GAME, "media", "dmd_hd_color", "palettes.json"))


@unittest.skipUnless(GENERATED, "HD colour media not generated (scripts/gen_media.py)")
class TestColorMedia(unittest.TestCase):
    def test_every_deff_has_a_palette(self):
        deffs = json.load(open(DATA, encoding="utf-8"))["deffs"]
        info = json.load(open(os.path.join(GAME, "media", "dmd_hd_color", "palettes.json"), encoding="utf-8"))
        cmap = dmd_color.load_colormap()
        self.assertEqual(145, len(deffs))
        for d in deffs:
            entry = info["deffs"]["deff_%03d" % int(d)]
            self.assertEqual(16, len(entry["palette"]))
            if entry["source"] != "serum":
                self.assertEqual("pup" if d in cmap["deffs"] else "default", entry["source"])
        if info.get("serum"):
            # the Serum colourisation colours most effects; the others keep their PuP hues
            serum = [e for e in info["deffs"].values() if e["source"] == "serum"]
            self.assertGreaterEqual(len(serum), 80)
            self.assertGreaterEqual(sum(e["serum_frames"] for e in serum), 1500)
            self.assertGreaterEqual(sum(e.get("capture_frames", 0) for e in serum), 150)
            self.assertGreaterEqual(sum(e["serum_frames"] + e.get("capture_frames", 0) + e["near_frames"]
                                        + e["shade_frames"] for e in serum), 2100)
            self.assertGreaterEqual(sum(1 for e in info["deffs"].values() if e["source"] == "pup"), 20)
        else:
            self.assertGreaterEqual(sum(1 for e in info["deffs"].values() if e["source"] == "pup"), 90)
            self.assertGreater(sum(1 for e in info["deffs"].values() if e.get("text_frames")), 20)

    def test_every_effect_frame_has_a_colour_twin(self):
        from PIL import Image
        frames = glob.glob(os.path.join(GAME, "media", "dmd", "deff_*", "f*.png"))
        self.assertGreater(len(frames), 1000)
        for src in frames:
            rel = os.path.relpath(src, os.path.join(GAME, "media", "dmd"))
            self.assertTrue(os.path.exists(os.path.join(GAME, "media", "dmd_hd_color", rel)), rel)
        for src in frames[::97]:
            rel = os.path.relpath(src, os.path.join(GAME, "media", "dmd"))
            big = Image.open(os.path.join(GAME, "media", "dmd_hd_color", rel))
            self.assertEqual("RGB", big.mode)
            w, h = Image.open(src).size
            self.assertEqual((w * dmd_color.COLOR_SCALE, h * dmd_color.COLOR_SCALE), big.size)
        self.assertEqual([], glob.glob(os.path.join(GAME, "media", "dmd_hd_color", "*", "solid*.png")))


class TestRunSwitch(unittest.TestCase):
    def test_dmd_color_arg(self):
        self.assertEqual(["--", "--dmd=hd", "--dmd-color=off"], run.dmd_args([], "hd", color="off"))
        self.assertEqual([], run.dmd_args([]))
        seen = {}
        with unittest.mock.patch.object(run, "run", lambda *a, **k: seen.update(k) or 0):
            run.main(["--dmd-color", "off", "--seconds", "1"])
        self.assertIn("--dmd-color=off", seen["godot_args"])


# Pixel hashes (sha1 of the RGBA pixels, 16 hex digits) of HD frames at 1280x320 rendered by phase11-hd
# (29b1b85: the Tron blue tint, no glow), before colour existed: --dmd-color=off must keep giving these.
# Effects without text nodes (their pictures only), times 0, 400 and 1600 ms.
HD_MONO = {
    "deff_046": ["67c19910553a69d7", "6ba267046ecc4cc3", "4bec6155c25801e6"],
    "deff_085": ["4c87418160015986", "488eea378d4a632c", "d68d9fb12d85cd64"],
}


@unittest.skipUnless(test_dmd_hd.CAN_RENDER, "needs Linux with Xvfb or a display, Godot and the imported media")
class TestGodotColor(unittest.TestCase):
    def render(self, slides, user_args=(), engine_args=(), env=None):
        out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, out, True)
        jobs = [{"slide": s, "kwargs": test_dmd_hd.KWARGS.get(s, {}), "times_ms": [0, 400, 1600],
                 "out": os.path.join(out, s)} for s in slides]
        job = os.path.join(out, "job.json")
        with open(job, "w") as f:
            json.dump(jobs, f)
        cmd = run.godot_command(["--rendering-driver", "opengl3"] + list(engine_args)
                                + ["res://tools/slide_capture.tscn", "--", "--job=" + job] + list(user_args))
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300,
                       env=dict(os.environ, **(env or {})))
        return out

    @staticmethod
    def frames(out, slide):
        from PIL import Image
        return [Image.open(p).convert("RGB") for p in sorted(glob.glob(os.path.join(out, slide, "*.png")))]

    def test_classic_ignores_colour(self):
        out = self.render(test_dmd_hd.CLASSIC, ["--dmd=classic", "--dmd-color=on"], env={"TRON_DMD_COLOR": "on"})
        got = {s: [hashlib.sha1(f.convert("RGBA").tobytes()).hexdigest()[:16] for f in self.frames(out, s)]
               for s in test_dmd_hd.CLASSIC}
        self.assertEqual(test_dmd_hd.CLASSIC, got)

    def test_colour_off_is_the_grey_hd_output(self):
        out = self.render(HD_MONO, ["--dmd=hd", "--dmd-color=off"], ["--resolution", "1280x320"])
        got = {s: [hashlib.sha1(f.convert("RGBA").tobytes()).hexdigest()[:16] for f in self.frames(out, s)]
               for s in HD_MONO}
        self.assertEqual(HD_MONO, got)

    def test_colour_on(self):
        import colorsys
        out = self.render(["deff_085"], ["--dmd=hd", "--dmd-color=on"], ["--resolution", "1280x320"])
        hues = set()
        for f in self.frames(out, "deff_085"):
            self.assertEqual((1280, 320), f.size)
            px = f.crop((420, 0, 1280, 320)).tobytes()
            for r, g, b in zip(px[0::3], px[1::3], px[2::3]):
                h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
                if s > 0.5 and v > 0.5:
                    hues.add("cool" if 0.45 < h < 0.7 else "warm" if h < 0.12 else "other")
        self.assertTrue({"cool", "warm"} <= hues, hues)               # orange cycles with cyan light lines


if __name__ == "__main__":
    unittest.main()
