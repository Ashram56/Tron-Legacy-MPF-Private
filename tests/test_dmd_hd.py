"""The HD DMD mode: the upscaler (scripts/dmd_hd.py), the HD fonts (scripts/gen_fonts.py build_hd), the HD
frames of every display effect (scripts/gen_media.py build_hd_frames), the run.py switches, and in Godot
(game/tools/dmd_mode.gd): classic mode gives the same 128x32 frames as before HD existed, dot for dot, and
HD mode draws the text at the window's resolution."""
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
import dmd_hd  # noqa: E402
import frame_text  # noqa: E402,F401
import gen_fonts  # noqa: E402
import run  # noqa: E402
import toolchain as tc  # noqa: E402

GAME = os.path.join(ROOT, "game")


def image(rows):
    from PIL import Image
    img = Image.new("L", (len(rows[0]), len(rows)))
    img.putdata([v for row in rows for v in row])
    return img


class TestUpscaler(unittest.TestCase):
    def test_sizes_and_flat_areas(self):
        black = image([[0] * 16] * 8)
        self.assertEqual((128, 64), dmd_hd.upscale_levels(black, 8).size)
        self.assertEqual((0, 0), dmd_hd.upscale_levels(black, 8).getextrema())
        block = image([[0] * 16] * 2 + [[0] * 4 + [255] * 8 + [0] * 4] * 4 + [[0] * 16] * 2)
        big = dmd_hd.upscale_levels(block, 8)
        self.assertEqual(255, big.getpixel((64, 32)))                  # inside the block: full level
        self.assertEqual(0, big.getpixel((8, 8)))                      # far outside: dark

    def test_shades_kept_and_edges_smoothed(self):
        rows = [[0] * 12 for _ in range(12)]
        for y in range(2, 10):
            for x in range(2, 10):
                rows[y][x] = 136 if x < 6 else 255                     # two shades side by side
        big = dmd_hd.upscale_levels(image(rows), 8)
        self.assertEqual(136, big.getpixel((3 * 8 + 4, 48)))
        self.assertEqual(255, big.getpixel((8 * 8 + 4, 48)))
        values = {v for _, v in big.getcolors(256)}
        self.assertGreater(len(values), 4)                             # anti-aliased edges, not 3 flat greys

    def test_single_dot_and_thin_line_survive(self):
        rows = [[0] * 9 for _ in range(9)]
        rows[4][4] = 255
        big = dmd_hd.upscale_levels(image(rows), 8)
        self.assertEqual(255, big.getpixel((36, 36)))
        line = [[0] * 20 for _ in range(5)]
        line[2] = [255] * 20
        big = dmd_hd.upscale_levels(image(line), 8)
        width = sum(1 for y in range(40) if big.getpixel((80, y)) >= 128)
        self.assertTrue(6 <= width <= 11, width)                       # about one dot (8 px) wide

    def test_deterministic(self):
        rows = [[(x * y * 37) % 256 // 17 * 17 for x in range(16)] for y in range(8)]
        a = dmd_hd.upscale_levels(image(rows), 4).tobytes()
        self.assertEqual(a, dmd_hd.upscale_levels(image(rows), 4).tobytes())


class TestHdFonts(unittest.TestCase):
    """Every one of the 44 ROM fonts has a vector (TrueType) twin whose every advance is the ROM's times the
    font units per dot, and a glow atlas with the same advances (scripts/font_outline.py)."""

    @classmethod
    def setUpClass(cls):
        cls.out = tempfile.mkdtemp()
        _, get, cls.fonts = gen_fonts.decode_all()
        cls.get = staticmethod(get)
        cls.built = gen_fonts.build_hd(cls.fonts, get, cls.out)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.out, ignore_errors=True)

    def ttf(self, n):
        from fontTools.ttLib import TTFont
        return TTFont(os.path.join(self.out, "rom_font_%02d.ttf" % n))

    def test_every_font_has_an_hd_font(self):
        self.assertTrue(self.built, "fontTools missing")
        self.assertEqual(44, len(self.fonts))
        info = json.load(open(os.path.join(self.out, "fonts_hd.json"), encoding="utf-8"))
        self.assertTrue(info["vector"])
        self.assertEqual(list(range(44)), [f["id"] for f in info["fonts"]])
        styles = {f["style"] for f in info["fonts"]}
        self.assertTrue({"plain", "outlined", "tron", "digits", "big tron digits"} <= styles, styles)
        self.assertTrue(info["fonts"][1]["outline"] and not info["fonts"][0]["outline"])
        for f in info["fonts"]:
            self.assertEqual("rom_font_%02d.ttf" % f["id"], f["file"])
            for name in (f["file"], f["glow"], f["glow"].replace(".fnt", ".png")):
                self.assertTrue(os.path.exists(os.path.join(self.out, name)), name)
        self.assertEqual([15], info["fonts"][13]["levels"])
        self.assertGreater(len(info["fonts"][42]["levels"]), 2)          # shaded big digits: a layer per level

    def test_advances_are_the_roms(self):
        """Every glyph of every plane (cell, lit dots, levels) of all 44 fonts: advance = ROM advance x units per
        dot, so every string's width and position is the ROM layout scaled up."""
        import font_outline as fo
        for f in self.fonts:
            font = self.ttf(f["id"])
            line = f["ascent"] + f["descent"]
            self.assertEqual(line * fo.UNITS, font["head"].unitsPerEm)
            self.assertEqual(f["ascent"] * fo.UNITS, font["hhea"].ascent)
            self.assertEqual(-f["descent"] * fo.UNITS, font["hhea"].descent)
            cmap = font.getBestCmap()
            levels = fo.font_levels(f, self.get) or [15]
            for c, g in f["glyphs"].items():
                rom = g["w"] + g["xoff"] + f["spacing"]
                codes = [ord(c), fo.CELL_PLANE + ord(c)] + [fo.LEVEL_PLANE + 0x100 * k + ord(c)
                                                             for k in range(1, len(levels))]
                for code in codes:
                    self.assertIn(code, cmap, (f["id"], c, hex(code)))
                    self.assertEqual(rom * fo.UNITS, font["hmtx"][cmap[code]][0], (f["id"], c, hex(code)))
            text = "".join(sorted(f["glyphs"]))
            self.assertEqual(sum(f["glyphs"][c]["w"] + f["glyphs"][c]["xoff"] + f["spacing"] for c in text)
                             - f["spacing"], gen_fonts.text_width(f, text))
            glow = {}
            for row in open(os.path.join(self.out, "rom_font_%02d_glow.fnt" % f["id"]), encoding="utf-8"):
                if row.startswith("char "):
                    kv = dict(p.split("=") for p in row.split()[1:])
                    glow[chr(int(kv["id"]))] = int(kv["xadvance"])
            self.assertEqual({c: (g["w"] + g["xoff"] + f["spacing"]) * fo.GLOW_SCALE for c, g in f["glyphs"].items()},
                             glow)

    def test_outlines(self):
        """Traced outlines: an O is an outer contour and a hole, wound as TrueType wants (outer clockwise), within
        its dots' box; a plain font's cell is its exact rectangle; outlined fonts' cells hold their lit dots."""
        import font_outline as fo
        from fontTools.pens.areaPen import AreaPen
        font = self.ttf(13)
        cmap = font.getBestCmap()
        glyf = font["glyf"]
        o = glyf[cmap[ord("O")]]
        self.assertEqual(2, o.numberOfContours)
        pen = AreaPen(font.getGlyphSet())
        font.getGlyphSet()[cmap[ord("O")]].draw(pen)
        self.assertLess(pen.value, 0)                                # clockwise outer contour (negative area)
        g = self.fonts[13]["glyphs"]["O"]
        o.recalcBounds(glyf)
        top = (g["h"] - g["below"]) * fo.UNITS
        self.assertTrue(-fo.UNITS // 2 <= o.xMin and o.xMax <= (g["w"] + 1) * fo.UNITS, (o.xMin, o.xMax))
        self.assertTrue(o.yMax <= top + fo.UNITS // 2, (o.yMax, top))
        cell = glyf[cmap[fo.CELL_PLANE + ord("O")]]
        cell.recalcBounds(glyf)
        self.assertTrue(cell.xMin <= o.xMin and cell.xMax >= o.xMax and cell.yMin <= o.yMin and cell.yMax >= o.yMax)
        plain = self.ttf(12)
        pc = plain.getBestCmap()
        box = plain["glyf"][pc[fo.CELL_PLANE + ord("A")]]
        box.recalcBounds(plain["glyf"])
        ga = self.fonts[12]["glyphs"]["A"]
        self.assertEqual((0, -ga["below"] * fo.UNITS, ga["w"] * fo.UNITS, (ga["h"] - ga["below"]) * fo.UNITS),
                         (box.xMin, box.yMin, box.xMax, box.yMax))
        self.assertEqual(1, box.numberOfContours)

    def test_deterministic(self):
        import font_outline as fo
        a = fo.glyph_contours(self.fonts[38], "S", self.get, [15])
        self.assertEqual(a, fo.glyph_contours(self.fonts[38], "S", self.get, [15]))
        self.assertTrue(all(len(c) >= 8 for c in a[ord("S")]))       # smooth: more than the dots' corners

    def test_glyph_cells(self):
        """Plain fonts keep their black cell (opaque rectangle); outline fonts are transparent around."""
        plain = dmd_hd.upscale_glyph(self.get(self.fonts[12]["glyphs"]["O"]["image"]), 8, False)
        self.assertEqual((255, 255), plain.split()[3].getextrema())
        outlined = dmd_hd.upscale_glyph(self.get(self.fonts[13]["glyphs"]["O"]["image"]), 8, True)
        self.assertEqual(0, outlined.split()[3].getpixel((0, 0)))
        self.assertEqual(255, outlined.split()[0].getextrema()[1])


GENERATED = os.path.exists(os.path.join(GAME, "media", "dmd_hd", "scale.json"))


@unittest.skipUnless(GENERATED, "HD media not generated (scripts/gen_media.py)")
class TestHdMedia(unittest.TestCase):
    def test_every_picture_has_an_hd_twin(self):
        from PIL import Image
        scale = json.load(open(os.path.join(GAME, "media", "dmd_hd", "scale.json")))["scale"]
        pictures = glob.glob(os.path.join(GAME, "media", "dmd", "deff_*", "*.png"))
        self.assertGreater(len(pictures), 1000)
        for src in pictures:
            rel = os.path.relpath(src, os.path.join(GAME, "media", "dmd"))
            dst = os.path.join(GAME, "media", "dmd_hd", rel)
            self.assertTrue(os.path.exists(dst), rel)
        for src in pictures[::50]:
            rel = os.path.relpath(src, os.path.join(GAME, "media", "dmd"))
            w, h = Image.open(src).size
            self.assertEqual((w * scale, h * scale), Image.open(os.path.join(GAME, "media", "dmd_hd", rel)).size)

    def test_every_deff_and_font(self):
        data = json.load(open(os.path.join(GAME, "tron", "media_data.json"), encoding="utf-8"))
        for deff in data["deffs"]:
            self.assertTrue(os.path.isdir(os.path.join(GAME, "media", "dmd_hd", "deff_%03d" % int(deff))), deff)
        for n in range(44):
            self.assertTrue(os.path.exists(os.path.join(GAME, "fonts", "hd", "rom_font_%02d.ttf" % n)))
            self.assertTrue(os.path.exists(os.path.join(GAME, "fonts", "hd", "rom_font_%02d_glow.fnt" % n)))


@unittest.skipUnless(GENERATED, "HD media not generated (scripts/gen_media.py)")
class TestFrameText(unittest.TestCase):
    """scripts/frame_text.py: the ROM-font text of the recorded effects, cleared from their HD frames and listed
    in media/dmd_hd/text.json for the HD mode to draw live."""

    @classmethod
    def setUpClass(cls):
        import frame_text
        cls.ft = frame_text
        cls.fonts = frame_text.load_fonts()
        cls.text = json.load(open(os.path.join(GAME, "media", "dmd_hd", "text.json"), encoding="utf-8"))

    def lines(self, deff, frame):
        from PIL import Image
        path = os.path.join(GAME, "media", "dmd", deff, frame)
        return [(t, fid, x, b) for t, fid, x, b, *_ in self.ft.frame_text(Image.open(path), self.fonts)]

    def test_finds_the_rom_text(self):
        self.assertEqual([("HIGH SCORE #1", 12, 43, 9), ("55,000,000", 12, 55, 29)], self.lines("deff_001", "f004.png")[:2])
        # O or 0 by the rest of the word
        self.assertIn(("50V / 20V DISABLED", 8, 16, 10), self.lines("deff_004", "f000.png"))
        self.assertIn(("PLEASE TRY AGAIN!", 12), [l[:2] for l in self.lines("deff_034", "f001.png")]
                      + [l[:2] for l in self.lines("deff_034", "f000.png")])

    def test_text_json_and_cleared_frames(self):
        from PIL import Image
        self.assertEqual([["BALL SAVED", 15]], [l[:2] for l in self.text["deff_020/f001.png"]])
        # a line half hidden by the art shows its letters at their place in the whole line
        part = [l for l in self.text["deff_063/f003.png"] if l[0] == "MULTIBALL"][0]
        self.assertEqual((3, 6), (part[6], part[7]))
        # the letters are gone from the HD frame (classic keeps them)
        t, fid, x, base, lv, w = self.text["deff_020/f001.png"][0][:6]
        cap = self.fonts[fid]["ascent"]
        classic = Image.open(os.path.join(GAME, "media", "dmd", "deff_020", "f001.png")).convert("L")
        hd = Image.open(os.path.join(GAME, "media", "dmd_hd", "deff_020", "f001.png")).convert("L")
        f = hd.width // 128
        self.assertGreater(classic.crop((x, base - cap + 1, x + w, base + 1)).getextrema()[1], 200)
        self.assertLess(hd.crop((x * f + f, (base - cap + 2) * f, (x + w - 1) * f, base * f)).getextrema()[1], 30)
        # pictures that are only rectangles (BALL SAVED's frame, the volume bars) are drawn as rectangles
        shapes = json.load(open(os.path.join(GAME, "media", "dmd_hd", "shapes.json"), encoding="utf-8"))
        self.assertEqual([[0, 0, 127, 31, 3, 0]], shapes["deff_020/f001.png"])
        self.assertLess(hd.getextrema()[1], 30)                      # nothing left of the picture
        self.assertTrue(all(r[5] == 1 for k, v in shapes.items() if k.startswith("deff_002/") for r in v))
        self.assertTrue(self.ft.shapes([[0] * 8, [0, 3, 3, 3, 0, 0, 0, 0], [0, 3, 0, 3, 0, 5, 0, 0], [0, 3, 3, 3, 0, 0, 0, 0]])
                        == [[1, 1, 3, 3, 3, 0], [5, 2, 5, 2, 5, 1]])
        self.assertIsNone(self.ft.shapes([[0, 7, 0], [7, 7, 7], [0, 7, 0]]))     # a cross is art
        # the ZEN zoom: the final line drawn larger on the frames before
        self.assertEqual([2.25], [l[8] for l in self.text["deff_100/f004.png"]])


class TestRunSwitches(unittest.TestCase):
    def test_dmd_args(self):
        self.assertEqual(["--", "--dmd=classic"], run.dmd_args([], "classic"))
        self.assertEqual(["--rendering-driver", "opengl3", "--resolution", "1920x480", "--", "--x", "--dmd=hd",
                          "--dmd-dots=2"],
                         run.dmd_args(["--rendering-driver", "opengl3", "--", "--x"], "hd", 2, "1920x480"))
        self.assertEqual([], run.dmd_args([]))                     # TRON_DMD / the project setting decide
        with self.assertRaises(SystemExit):
            run.dmd_args([], size="big")
        self.assertEqual(["--", "--dmd-text-color=#ff0000", "--dmd-text-glow=0"],
                         run.dmd_args([], text_color="ff0000", text_glow=0.0))
        with self.assertRaises(SystemExit):
            run.dmd_args([], text_color="blue")
        self.assertEqual(["--", "--dmd-tint=orange"], run.dmd_args([], tint="orange"))
        self.assertEqual(["--", "--dmd-font=orbitron"], run.dmd_args([], font="orbitron"))
        self.assertEqual(["--", "--dmd-text-scale=0.9"], run.dmd_args([], text_scale=0.9))
        with self.assertRaises(SystemExit):
            run.dmd_args([], text_scale=3.0)
        ttf = os.path.join(GAME, "fonts_ttf", "Orbitron.ttf")
        self.assertEqual(["--", "--dmd-font=" + os.path.abspath(ttf)],
                         run.dmd_args([], font=os.path.relpath(ttf)))      # a font file: its absolute path

    def test_clean_fonts_shipped(self):
        """The clean fonts are in the repository with their licences (SIL Open Font License)."""
        for name in ["Rajdhani-Bold.ttf", "Orbitron.ttf", "OFL-Rajdhani.txt", "OFL-Orbitron.txt"]:
            self.assertTrue(os.path.exists(os.path.join(GAME, "fonts_ttf", name)), name)

    def test_cli(self):
        seen = {}
        with unittest.mock.patch.object(run, "run", lambda *a, **k: seen.update(k) or 0):
            run.main(["--dmd", "classic", "--seconds", "1"])
            self.assertIn("--dmd=classic", seen["godot_args"])
            run.main(["--seconds", "1"])
            self.assertEqual([], seen["godot_args"])
            run.main(["--seconds", "1", "--dmd-text-color", "#2a6cff", "--dmd-text-glow", "1.5"])
            self.assertEqual(["--", "--dmd-text-color=#2a6cff", "--dmd-text-glow=1.5"], seen["godot_args"])
            run.main(["--seconds", "1", "--dmd-tint", "orange"])
            self.assertEqual(["--", "--dmd-tint=orange"], seen["godot_args"])
            run.main(["--seconds", "1", "--dmd-font", "rom"])
            self.assertEqual(["--", "--dmd-font=rom"], seen["godot_args"])


# Pixel hashes (sha1 of the RGBA dots, 16 hex digits) of 128x32 frames rendered before the HD mode existed
# (phase10-docker 662f0a8; deff 46 re-taken at 38a1bf2, whose status panel changed): classic mode must keep
# giving these. Times 0, 400 and 1600 ms.
CLASSIC = {
    "deff_019": ["4c202f8e88fbe459", "ceff80ed506ad992", "ceff80ed506ad992"],
    "deff_025": ["d37ed2eab53a1001", "d37ed2eab53a1001", "d37ed2eab53a1001"],
    "deff_046": ["669370d0afb62c1d", "46317d7624939fbf", "3e055f3406cf6f2d"],
    "deff_091": ["5389647d8fd053ff", "5389647d8fd053ff", "0b25fcc7236c9b02"],
    "deff_143": ["6507f3260bdb28ac", "c3c251af5390289d", "2b45f48506dd629c"],
}
KWARGS = {"deff_019": {"line0": "BALL 1", "line1": "1,234,560", "credits": "FREE PLAY",
                       "replay": "REPLAY AT 20,000,000", "p1": "1,234,560", "p2": "870,050", "p3": "", "p4": "",
                       "players": 2, "player": 1, "valid": True, "award": "25,000", "award_age": 3,
                       "blink_age": 0, "bar_ds": 6, "bar_zfs": 7},
          "deff_025": {"line1": "50,000"}, "deff_046": {}, "deff_091": {"lit": 3, "new": 4},
          "deff_143": {"line2": "25,000,000"}}
# the args of an earlier show of each slide, for a slide reused from the pool (tron/dmd_slide.gd)
REUSE_KWARGS = {"deff_019": {"line0": "BALL 3", "line1": "98,765,430", "credits": "CREDITS 2", "replay": "",
                             "p1": "1", "p2": "2", "p3": "3", "p4": "98,765,430", "players": 4, "player": 4,
                             "valid": False, "award": "1,000,000", "award_age": 0, "blink_age": 70,
                             "bar_ds": 10, "bar_clu": 9, "bar_gem": 4},
                "deff_025": {"line1": "7,777,777"}, "deff_046": {}, "deff_091": {"lit": 15, "new": 1},
                "deff_143": {"line2": "1"}}
CAN_RENDER = (sys.platform.startswith("linux") and GENERATED and os.path.exists(tc.godot_path())
              and (shutil.which("xvfb-run") or os.environ.get("DISPLAY"))
              and not tc.media_stale())


@unittest.skipUnless(CAN_RENDER, "needs Linux with Xvfb or a display, Godot and the imported media")
class TestGodotModes(unittest.TestCase):
    """Renders slides with game/tools/slide_capture.tscn, as scripts/render_diff.py does."""

    def render(self, user_args=(), engine_args=(), env=None, machine_vars=None, slides=CLASSIC, reuse=False):
        out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, out, True)
        jobs = [{"slide": s, "kwargs": KWARGS[s], "times_ms": [0, 400, 1600], "out": os.path.join(out, s),
                 "machine_vars": machine_vars or {}} for s in slides]
        for j in jobs if reuse else []:
            j["reuse_kwargs"] = REUSE_KWARGS[j["slide"]]
        job = os.path.join(out, "job.json")
        with open(job, "w") as f:
            json.dump(jobs, f)
        cmd = run.godot_command(["--rendering-driver", "opengl3"] + list(engine_args)
                                + ["res://tools/slide_capture.tscn", "--", "--job=" + job] + list(user_args))
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300,
                       env=dict(os.environ, **(env or {})))
        return out

    def hashes(self, out):
        from PIL import Image
        got = {}
        for s in CLASSIC:
            got[s] = [hashlib.sha1(Image.open(p).convert("RGBA").tobytes()).hexdigest()[:16]
                      for p in sorted(glob.glob(os.path.join(out, s, "*.png")))]
        return got

    def test_classic_is_the_original_output(self):
        self.assertEqual(CLASSIC, self.hashes(self.render(["--dmd=classic"])))
        # captures without --dmd stay classic, even with TRON_DMD=hd (the ROM checks compare dots)
        self.assertEqual(CLASSIC, self.hashes(self.render(env={"TRON_DMD": "hd"})))
        # the HD text font never touches classic
        self.assertEqual(CLASSIC, self.hashes(self.render(["--dmd=classic", "--dmd-font=orbitron"])))

    def test_reused_slide_renders_as_new(self):
        """A display effect's slide kept from an earlier show (tron/dmd_slide.gd, GMC's slide pool) renders exactly as
        one just built: the ROM's frames in classic, the same pixels in HD (text, panel, letters, animation)."""
        self.assertEqual(CLASSIC, self.hashes(self.render(["--dmd=classic"], reuse=True)))
        hd = (["--dmd=hd"], ["--resolution", "512x128"])
        self.assertEqual(self.hashes(self.render(*hd)), self.hashes(self.render(*hd, reuse=True)))

    def test_effect_data_and_node_scenes_agree(self):
        """Every display effect is drawn from its data (media/dmd/<name>/effect.json, tron/dmd_screen.gd); its node
        scene (tron/dmd/renderer="nodes") draws the same ROM frames, and a custom scene res://dmd_custom/<name>.tscn
        is shown instead of either, with the effect's event args."""
        self.assertEqual(CLASSIC, self.hashes(self.render(["--dmd=classic"], env={"TRON_DMD_RENDERER": "nodes"})))
        custom = os.path.join(GAME, "dmd_custom", "deff_025.tscn")
        self.assertFalse(os.path.exists(custom))
        os.makedirs(os.path.dirname(custom), exist_ok=True)
        self.addCleanup(os.remove, custom)
        with open(custom, "w") as f:      # one text line where deff 25 has two, a white box over the left half
            f.write('''[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://tron/rom_text.gd" id="text"]

[node name="custom" type="Control"]
layout_mode = 3
anchors_preset = 0
offset_right = 128.0
offset_bottom = 32.0

[node name="Box" type="ColorRect" parent="."]
offset_right = 64.0
offset_bottom = 32.0
color = Color(1, 1, 1, 1)

[node name="Line1" type="Label" parent="."]
theme_override_colors/font_color = Color(1, 0.45, 0.05, 1)
script = ExtResource("text")
variable_type = 1
variable_name = "line1"
rom_font = 15
rom_x = 96
rom_y = 26
rom_flags = 2
''')
        from PIL import Image
        out = self.render(["--dmd=classic"], slides=["deff_025"])
        img = Image.open(os.path.join(out, "deff_025", "frame_00000.png")).convert("RGB")
        self.assertEqual((255, 255, 255), img.getpixel((10, 10)))
        right = img.crop((64, 0, 128, 32)).convert("L").point(lambda p: 255 if p > 40 else 0).getbbox()
        self.assertTrue(right and abs((64 + right[0] + 64 + right[2]) / 2 - 96.5) < 3, right)   # "50,000" about x 96

    def test_hd_draws_text_at_window_resolution(self):
        from PIL import Image
        out = self.render(["--dmd=hd", "--dmd-text-glow=0", "--dmd-text-scale=1"], ["--resolution", "1280x320"])
        frame = Image.open(os.path.join(out, "deff_025", "frame_00000.png")).convert("L")
        self.assertEqual((1280, 320), frame.size)
        box = frame.point(lambda p: 255 if p > 40 else 0).getbbox()
        # "50,000" in font 15, centred on x 84, baseline row 26 (deff 25): 42 x 11 dots in classic
        self.assertTrue(abs((box[0] + box[2]) / 2 - 84.5 * 10) < 15, box)
        self.assertTrue(380 < box[2] - box[0] < 450 and 90 < box[3] - box[1] < 130, box)
        self.assertGreater(len(frame.getcolors(256)), 20)          # smooth edges, not 10x10 blocks
        score = Image.open(os.path.join(out, "deff_019", "frame_00002.png"))
        self.assertEqual((1280, 320), score.size)

    def test_clean_fonts_keep_the_rom_layout(self):
        """HD text in a clean font (default rajdhani) sits in the ROM's box: as tall as the ROM's capitals, centred
        where the ROM centres, never wider than the ROM's text (orbitron, wider, is squeezed); --dmd-font=rom
        and TRON_DMD_FONT=rom give the ROM's traced dots instead, a missing font file falls back to them."""
        from PIL import Image

        def box(out, slide="deff_025"):
            frame = Image.open(os.path.join(out, slide, "frame_00000.png")).convert("L")
            return frame.point(lambda p: 255 if p > 90 else 0).getbbox(), frame
        boxes = {}
        for font in ["rajdhani", "orbitron", "godot", "rom"]:
            b, frame = box(self.render(["--dmd=hd", "--dmd-text-glow=0", "--dmd-text-scale=1", "--dmd-font=" + font],
                                       ["--resolution", "1280x320"]))
            boxes[font] = b
            # "50,000", font 15: centred on x 84 (dots, 10 px each), 42 dots wide, capitals 10 dots high on row 26
            self.assertTrue(abs((b[0] + b[2]) / 2 - 84.5 * 10) < 15, (font, b))
            self.assertLessEqual(b[2] - b[0], 420, (font, b))
            self.assertTrue(abs(b[1] - 170) <= 8, (font, b))              # capitals' top: row 17
            self.assertGreater(len(frame.getcolors(256)), 20, font)      # smooth edges
        self.assertEqual(len({boxes[f] for f in boxes}), 4, boxes)          # four different looks
        self.assertEqual(boxes["rajdhani"], box(self.render(["--dmd=hd", "--dmd-text-glow=0"], ["--resolution", "1280x320"],
                                                            env={"TRON_DMD_TEXT_SCALE": "1"}))[0])
        # the default size, 0.85: smaller, about the same middle
        b, _ = box(self.render(["--dmd=hd", "--dmd-text-glow=0"], ["--resolution", "1280x320"]))
        full = boxes["rajdhani"]
        self.assertTrue(0.8 < (b[2] - b[0]) / (full[2] - full[0]) < 0.9, (b, full))
        self.assertTrue(abs((b[0] + b[2]) - (full[0] + full[2])) <= 6, (b, full))
        self.assertEqual(boxes["rom"], box(self.render(["--dmd=hd", "--dmd-text-glow=0"], ["--resolution", "1280x320"],
                                                       env={"TRON_DMD_FONT": "rom"}))[0])
        self.assertEqual(boxes["rom"], box(self.render(["--dmd=hd", "--dmd-text-glow=0", "--dmd-font=/nowhere/x.ttf"],
                                                       ["--resolution", "1280x320"]))[0])

    def test_service_menu_glow_and_size(self):
        """The service menu's DISPLAY ADJUSTMENTS (MPF machine vars dmd_text_glow, dmd_text_size, in percent)
        restyle the text already shown: size 100 = --dmd-text-scale=1, glow 0 = --dmd-text-glow=0; -1 keeps
        the start value; classic ignores them."""
        from PIL import Image, ImageStat

        def frame(out):
            return Image.open(os.path.join(out, "deff_025", "frame_00000.png")).convert("RGB")

        def box(img):
            return img.convert("L").point(lambda p: 255 if p > 90 else 0).getbbox()
        hd = ["--resolution", "1280x320"]
        full = frame(self.render(["--dmd=hd", "--dmd-text-glow=0", "--dmd-text-scale=1"], hd, slides=["deff_025"]))
        plain = frame(self.render(["--dmd=hd"], hd, slides=["deff_025"]))
        got = frame(self.render(["--dmd=hd"], hd, machine_vars={"dmd_text_glow": 0, "dmd_text_size": 100},
                                slides=["deff_025"]))
        self.assertEqual(box(full), box(got))
        self.assertEqual(full.tobytes(), got.tobytes())
        same = frame(self.render(["--dmd=hd"], hd, machine_vars={"dmd_text_glow": -1, "dmd_text_size": -1},
                                 slides=["deff_025"]))
        self.assertEqual(plain.tobytes(), same.tobytes())
        big_glow = frame(self.render(["--dmd=hd"], hd, machine_vars={"dmd_text_glow": 200}, slides=["deff_025"]))
        light = [sum(ImageStat.Stat(img.convert("L")).sum) for img in (got, plain, big_glow)]   # no glow, 80%, 200%
        self.assertTrue(light[0] < light[1] < light[2], light)
        self.assertEqual(CLASSIC, self.hashes(self.render(["--dmd=classic"], machine_vars={"dmd_text_glow": 300,
                                                                                         "dmd_text_size": 50})))

    def test_recorded_text_drawn_live(self):
        """HD: the text of a recorded effect (deff 20, BALL SAVED) is drawn live in the clean font at its place:
        smooth, in the text colour, centred where the ROM's line is."""
        from PIL import Image
        out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, out, True)
        job = os.path.join(out, "job.json")
        with open(job, "w") as f:
            json.dump([{"slide": "deff_020", "times_ms": [0], "out": os.path.join(out, "hd")}], f)
        subprocess.run(run.godot_command(["--rendering-driver", "opengl3", "--resolution", "1280x320",
                                          "res://tools/slide_capture.tscn", "--", "--job=" + job, "--dmd=hd",
                                          "--dmd-text-glow=0"]),
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300)
        frame = Image.open(os.path.join(out, "hd", "frame_00000.png")).convert("RGB")
        text = json.load(open(os.path.join(GAME, "media", "dmd_hd", "text.json"), encoding="utf-8"))
        first = sorted(k for k in text if k.startswith("deff_020/"))[0]
        line = [l for l in text[first] if l[0] == "BALL SAVED"][0]
        top = frame.crop((0, 0, 1280, 160)).convert("L").point(lambda p: 255 if p > 60 else 0).getbbox()
        self.assertTrue(abs((top[0] + top[2]) / 2 - (line[2] + line[5] / 2) * 10) < 20, (top, line))
        self.assertGreater(len(frame.getcolors(1 << 16)), 20)
        px = frame.load()
        core = [px[x, y] for x in range(top[0], top[2]) for y in range(top[1], top[3]) if px[x, y][2] > 200]
        self.assertTrue(core and all(b > r for r, g, b in core))

    def test_hd_default_is_single_colour(self):
        """The HD animations are in the DMD's one colour (Tron blue, level for level), never multicoloured:
        every lit pixel of the deff 46 animation is a shade of #2a6cff."""
        from PIL import Image
        out = self.render(["--dmd=hd"], ["--resolution", "1280x320"])
        paths = sorted(glob.glob(os.path.join(out, "deff_046", "*.png")))
        self.assertEqual(3, len(paths))
        for path in paths:
            img = Image.open(path).convert("RGB")
            px = [p for p in img.getdata() if max(p) > 40]
            self.assertTrue(px)
            for r, g, b in px[::50]:
                self.assertTrue(abs(r / b - 0x2a / 0xff) < 0.08 and abs(g / b - 0x6c / 0xff) < 0.08, (r, g, b))
        self.assertFalse(os.path.exists(os.path.join(GAME, "media", "dmd_hd_color")))

    def test_text_style(self):
        """HD text is in the text colour (default the Tron blue #2a6cff), with a glow of the glow colour by default
        (--dmd-text-glow=0 takes it away); the effect frames, the letters and the score panel follow;
        --dmd-tint=orange is the original colour; --dmd-text-color / TRON_DMD_TEXT_GLOW change them."""
        from PIL import Image

        def strokes(path):
            img = Image.open(path).convert("RGB")
            px = img.load()
            return img, px
        out = self.render(["--dmd=hd", "--dmd-text-glow=0"], ["--resolution", "1280x320"])
        img, px = strokes(os.path.join(out, "deff_025", "frame_00000.png"))
        core = [px[x, y] for x in range(img.width) for y in range(img.height) if px[x, y][2] > 200]
        self.assertGreater(len(core), 2000)
        common = max(set(core), key=core.count)
        self.assertTrue(all(abs(a - b) <= 3 for a, b in zip(common, (0x2a, 0x6c, 0xff))), common)
        box = Image.open(os.path.join(out, "deff_025", "frame_00000.png")).convert("L").point(
            lambda p: 255 if p > 90 else 0).getbbox()
        self.assertEqual({(0, 0, 0)}, {px[x, box[1] - 8] for x in range(box[0], box[2])})   # no glow
        letters, lp = strokes(os.path.join(out, "deff_091", "frame_00002.png"))
        lit = [lp[x, y] for x in range(0, letters.width, 3) for y in range(0, letters.height, 3) if sum(lp[x, y]) > 200]
        self.assertTrue(lit and all(b >= r for r, g, b in lit))                 # blue letters, no orange
        art, ap = strokes(os.path.join(out, "deff_046", "frame_00002.png"))
        lit = [ap[x, y] for x in range(0, art.width, 3) for y in range(0, art.height, 3) if sum(ap[x, y]) > 200]
        self.assertTrue(lit and all(b > r for r, g, b in lit))                  # the animation too
        # the original orange: text and animation
        out = self.render(["--dmd=hd", "--dmd-tint=orange"], ["--resolution", "1280x320"])
        img, px = strokes(os.path.join(out, "deff_025", "frame_00000.png"))
        core = [px[x, y] for x in range(img.width) for y in range(img.height) if px[x, y][0] > 200]
        self.assertGreater(len(core), 2000)
        self.assertTrue(all(abs(a - b) <= 3 for a, b in zip(max(set(core), key=core.count), (0xff, 0x73, 0x0d))))
        art, ap = strokes(os.path.join(out, "deff_046", "frame_00002.png"))
        lit = [ap[x, y] for x in range(0, art.width, 3) for y in range(0, art.height, 3) if sum(ap[x, y]) > 200]
        self.assertTrue(lit and all(r > b for r, g, b in lit))
        # the default glow: blue-cyan light around the strokes
        out = self.render(["--dmd=hd"], ["--resolution", "1280x320"])
        img, px = strokes(os.path.join(out, "deff_025", "frame_00000.png"))
        halo = [px[x, box[1] - 8] for x in range(box[0], box[2])]
        self.assertTrue(any(b > 30 and b > r for r, g, b in halo), halo[::40])
        # other colour, no glow
        out = self.render(["--dmd=hd", "--dmd-text-color=#ff0000"], ["--resolution", "1280x320"],
                          env={"TRON_DMD_TEXT_GLOW": "0"})
        img, px = strokes(os.path.join(out, "deff_025", "frame_00000.png"))
        colours = {px[x, y] for x in range(img.width) for y in range(img.height)}
        self.assertIn((255, 0, 0), colours)
        self.assertTrue(all(g == 0 and b == 0 for r, g, b in colours if r > 0), sorted(colours)[-5:])


GODOT_FONTS = (os.path.exists(tc.godot_path()) and os.path.exists(os.path.join(GAME, "fonts", "hd", "fonts_hd.json"))
               and os.path.exists(os.path.join(GAME, "fonts", "fonts.json")))


@unittest.skipUnless(GODOT_FONTS, "needs Godot and the generated HD fonts (scripts/gen_media.py)")
class TestGodotFonts(unittest.TestCase):
    def test_godot_advances_are_the_roms(self):
        """As Godot lays them out (game/tools/font_check.gd), at the size the DMD draws them: every character of
        all 44 vector fonts and of their glow fonts advances by the ROM's dots, and a string by their sum."""
        out = subprocess.run([tc.godot_path(), "--headless", "--path", GAME, "--script", "res://tools/font_check.gd"],
                             capture_output=True, text=True, timeout=300).stdout
        line = [r for r in out.splitlines() if r.startswith("FONT_CHECK ")]
        self.assertTrue(line, out[-2000:])
        got = json.loads(line[0][len("FONT_CHECK "):])
        fonts = json.load(open(os.path.join(GAME, "fonts", "fonts.json"), encoding="utf-8"))["fonts"]
        self.assertEqual(44, len(got))
        for f in fonts:
            g = got[str(f["id"])]
            rom = {c: g_["w"] + g_["xoff"] + f["spacing"] for c, g_ in f["glyphs"].items()}
            self.assertEqual({c: [float(a)] * 3 for c, a in rom.items()}, g["advances"], f["id"])
            self.assertEqual(sum(rom.values()), g["all"], f["id"])
            self.assertEqual(f["ascent"], g["ascent"], f["id"])
            self.assertEqual(f["descent"], g["descent"], f["id"])

if __name__ == "__main__":
    unittest.main()
