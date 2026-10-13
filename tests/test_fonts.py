"""ROM fonts (scripts/gen_fonts.py) and the text layout of the display effects (scripts/rom_layout.py)."""
import json
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "game"))
import gen_fonts  # noqa: E402
import rom_layout  # noqa: E402
import render_diff  # noqa: E402


class TestFontDecoding(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        index, get, cls.fonts = gen_fonts.decode_all()
        cls.get = staticmethod(get)

    def test_font_table(self):
        self.assertEqual(44, len(self.fonts))
        self.assertEqual(218, self.fonts[0]["group"])            # first font: 5 px, images 218-276
        self.assertEqual(928, self.fonts[12]["group"])
        self.assertEqual(2241, self.fonts[33]["group"])           # the most used font in the deffs

    def test_known_glyphs(self):
        e = self.fonts[12]["glyphs"]["E"]                         # 8 px plain font: E is 6x8, advance 7
        self.assertEqual((6, 8, 0), (e["w"], e["h"], e["below"]))
        self.assertEqual(1, self.fonts[12]["spacing"])
        self.assertEqual(-1, self.fonts[13]["spacing"])           # outlined twin of font 12
        self.assertEqual(-1, self.fonts[15]["glyphs"][","]["xoff"])
        self.assertEqual(1, self.fonts[15]["glyphs"][","]["below"])
        self.assertNotIn("$", self.fonts[0]["glyphs"])            # font 0 has no dollar sign
        self.assertNotIn("#", self.fonts[4]["glyphs"])
        self.assertEqual(list(",0123456789"), list(self.fonts[26]["glyphs"]))
        self.assertEqual(42, gen_fonts.text_width(self.fonts[15], "50,000") + 1)

    def test_bmfont(self):
        out = os.path.join(ROOT, "captures", "test_fonts")
        os.makedirs(out, exist_ok=True)
        name = gen_fonts.write_bmfont(self.fonts[12], self.get, out)
        with open(os.path.join(out, name + ".fnt"), encoding="utf-8") as f:
            body = f.read()
        self.assertIn("common lineHeight=9 base=8", body)        # 8 rows above the baseline, comma 1 below
        self.assertIn("char id=69 ", body)
        self.assertIn("xadvance=7 page=0", [l for l in body.splitlines() if l.startswith("char id=69 ")][0])

    def test_rom_text_matches_reference(self):
        """TOTAL BONUS / 50,000 drawn like the ROM equals the emulator capture of deff 25."""
        ref, _ = render_diff.reference(25)
        canvas = [[None] * 128 for _ in range(32)]
        gen_fonts.render(self.get, self.fonts[12], "TOTAL BONUS", 84, 12, 2, canvas)
        gen_fonts.render(self.get, self.fonts[15], "50,000", 84, 26, 2, canvas)
        dots = {(x, y): v for y in range(32) for x in range(128) if (v := canvas[y][x]) is not None}
        best = max(sum(r[y][x] == v for (x, y), v in dots.items()) for r in ref)
        self.assertEqual(len(dots), best)

    def test_font0_comma(self):
        """Score display replay line: font 0's comma also sits one dot left (deff 19 capture)."""
        ref, _ = render_diff.reference(19)
        canvas = [[None] * 128 for _ in range(32)]
        gen_fonts.render(self.get, self.fonts[0], "REPLAY AT 20,000,000", 84, 30, 2, canvas)
        dots = {(x, y): v for y in range(32) for x in range(128) if (v := canvas[y][x]) is not None}
        self.assertEqual(len(dots), max(sum(r[y][x] == v for (x, y), v in dots.items()) for r in ref))


def effect_scene(name):
    """An effect's node scene: media/dmd/<name>/nodes.tscn (the slide in slides/deffs/ is a proxy that draws the
    effect from its effect.json), or the slide itself before the data renderer."""
    nodes = os.path.join(ROOT, "game", "media", "dmd", name, "nodes.tscn")
    return nodes if os.path.exists(nodes) else os.path.join(ROOT, "game", "slides", "deffs", name + ".tscn")


class TestLayout(unittest.TestCase):

    def test_draw_calls(self):
        calls = rom_layout.deff_calls()
        self.assertIn({"text": "EXTRA", "font": 13, "flags": 4, "x": 127, "y": 10}, calls[133])
        fit = [c for c in calls[40] if c["text"] == "YOU'RE UP"][0]
        self.assertEqual(("0x040d2aa4", 85), (fit["font_list"], fit["max_width"]))

    def test_alternate_layout(self):
        fonts = gen_fonts.decode_all()[2]
        lays = rom_layout.line_layouts(133, ["EXTRA", "BALL", "%,02lu"], fonts)
        self.assertEqual((127, 14, "line2"), (lays[0]["alt_x"], lays[0]["alt_y"], lays[0]["alt_when_empty"]))

    def test_timed_lines(self):
        fonts = gen_fonts.decode_all()[2]
        match = rom_layout.line_layouts(38, ["MATCH", "%,02lu", "%,02lu"], fonts)
        self.assertEqual((37, 0, 15), (match[0]["font"], match[0]["level_steps"][0], match[0]["level_steps"][-1]))
        self.assertEqual(rom_layout.frame_ms(38, 64), match[1]["show_after_ms"])   # number at loop frame 0x40
        self.assertGreater(match[1]["show_after_ms"], match[0]["hide_after_ms"])
        up = rom_layout.line_layouts(40, ["PLAYER %d", "YOU'RE UP"], fonts)
        self.assertEqual(round(6 * rom_layout.TICK_MS), up[1]["blink_ms"])

    def test_panels(self):
        panels = rom_layout.status_panel_deffs()
        self.assertEqual("status", panels[19])
        self.assertEqual("status", panels[133])
        self.assertEqual("match", panels[38])

    def test_effect_fills(self):
        """deff 95 clears a black band under ALL TARGETS= after drawing its bitmap (FUN_000274c0); deff 96
        draws the same screen from the task it spawns (FUN_01032a30)."""
        fills = rom_layout.effect_fills()
        self.assertEqual([(41, 26, 127, 31)], fills[95])
        self.assertEqual([(41, 26, 127, 31)], fills[96])
        self.assertEqual([(41, 26, 127, 31)], fills[98])
        self.assertNotIn(19, fills)                     # the score display's panel clears are not effect fills

    def test_twin_line(self):
        """deff 95 prints the timer twice in a row, left at x 42 and right-aligned at x 127."""
        fonts = gen_fonts.decode_all()[2]
        lays = rom_layout.line_layouts(95, ["%u", "ALL TARGETS=%,02lu"], fonts)
        self.assertEqual((1, 42, 1, {"x": 127, "flags": 4}),
                         (lays[0]["font"], lays[0]["x"], lays[0]["flags"], lays[0]["twin"]))

    def test_stacked_outline_lines(self):
        """Mode totals stack outlined lines one row into each other (deff 90 at y 6, 12, 20): every line
        shows (MULTIBALL, SIMULATION and the SOS totals were dropped as overlapping)."""
        fonts = gen_fonts.decode_all()[2]
        for deff_id, lines in ((90, ["LIGHT CYCLE", "MULTIBALL", "TOTAL:", "%,02lu"]),
                               (126, ["SEA OF", "SIMULATION", "TOTAL:", "%,02lu"]),
                               (125, ["SEA OF", "SIMULATION", "COMPLETED", "%,02lu"]),
                               (70, ["QUORRA", "MULTIBALL", "TOTAL:", "%,02lu"])):
            lays = rom_layout.line_layouts(deff_id, lines, fonts)
            self.assertTrue(all(lays), (deff_id, lays))
        # screens of one effect drawn at the same place still exclude each other
        lays = rom_layout.line_layouts(91, ["COLLECT", "FOR FASTSCORING", "COLLECT", "FOR SOS ITEM"], fonts)
        self.assertEqual([True, True, False, False], [bool(x) for x in lays])

    def test_zuse_intro_screens(self):
        """deff 94 shows ZUSE / FAST SCORING blinking, then ALL TARGETS / SCORE / POINTS: never both
        (the slide drew every line at once over the letters)."""
        fonts = gen_fonts.decode_all()[2]
        lays = rom_layout.line_layouts(94, ["FAST SCORING", "ALL TARGETS", "SCORE", "%,02lu POINTS"], fonts)
        self.assertTrue(all(lays))
        self.assertLessEqual(lays[0]["hide_after_ms"], min(x["show_after_ms"] for x in lays[1:]))
        self.assertEqual([34, 10, 17, 10], [x["font"] for x in lays])
        self.assertEqual([4], lays[1]["level_steps"])

    def test_spawned_display_task_text(self):
        """deff 96's timer and ALL TARGETS= come from the task it spawns (FUN_01032a30)."""
        fonts = gen_fonts.decode_all()[2]
        lays = rom_layout.line_layouts(96, ["%luK", "%u", "ALL TARGETS=%,02lu"], fonts)
        self.assertEqual([39, 1, 0], [x["font"] for x in lays])
        self.assertEqual((85, 31), (lays[2]["x"], lays[2]["y"]))

    def test_table_messages(self):
        """deff 114 draws the stage's two messages from the stage table under SEA OF SIMULATION."""
        fonts = gen_fonts.decode_all()[2]
        lays = rom_layout.line_layouts(114, ["SEA OF", "SIMULATION", "%s", "%s"], fonts)
        self.assertEqual([(84, 8), (84, 14), (84, 23), (84, 29)], [(x["x"], x["y"]) for x in lays])

    def test_loop_period(self):
        import gen_media
        from PIL import Image
        imgs = [Image.new("RGBA", (128, 32), (k * 10, 0, 0, 255)) for k in range(3)]
        frames = [(imgs[k % 3], 49) for k in range(8)]           # 2 2/3 cycles, cut mid-cycle
        self.assertEqual(3, gen_media.loop_period(frames))
        self.assertIsNone(gen_media.loop_period([(imgs[k], 49) for k in range(3)]))

    def test_letter_positions_match_rom_frames(self):
        """The letter bitmaps of deffs 91, 92 and 107 sit where the ROM draws them: every dot of the
        hollow (91, 107) or solid (92) image equals the deff's graphics frame at x 42 + 21 i, y 5."""
        import glob
        import io
        import zipfile
        import gen_media
        from PIL import Image
        z = zipfile.ZipFile(os.path.join(ROOT, "assets", "mpf_package", "media", "rom_images_all.zip"))
        for deff_id, offset in ((91, 10), (92, 0), (107, 10)):
            spec = gen_media.LETTER_DEFFS[deff_id]
            frame = Image.open(glob.glob(os.path.join(ROOT, "assets", "mpf_package", "media", "dmd",
                                                      "deff_%03d_*" % deff_id, "frames", "000.png"))[0]).convert("L")
            for i, solid in enumerate(spec["images"]):
                img = Image.open(io.BytesIO(z.read("%04d.png" % (solid + offset)))).convert("RGBA")
                x0, y0 = gen_media.LETTER_X + gen_media.LETTER_DX * i, gen_media.LETTER_Y
                for y in range(img.height):
                    for x in range(img.width):
                        r, _, _, a = img.getpixel((x, y))
                        if a:
                            self.assertEqual(r > 0, frame.getpixel((x0 + x, y0 + y)) > 0, (deff_id, i, x, y))

    def test_letter_slides(self):
        path = os.path.join(ROOT, "game", "tron", "media_data.json")
        if not os.path.exists(path):
            self.skipTest("media data not generated (scripts/gen_media.py)")
        deffs = json.load(open(path, encoding="utf-8"))["deffs"]
        self.assertEqual(("letters", ["lit", "new"]), (deffs["91"]["source"], deffs["91"]["args"]))
        self.assertEqual(["old", "new"], deffs["107"]["args"])
        slide = effect_scene("deff_091")
        if os.path.exists(slide):
            with open(slide, encoding="utf-8") as f:
                body = f.read()
            for node in ("Solid0", "Hollow3", "LetterPanel"):
                self.assertIn('[node name="%s"' % node, body)
            self.assertIn("res://tron/letter_panel.gd", body)
            self.assertNotIn("reference_capture", body)
        slide = effect_scene("deff_095")
        if os.path.exists(slide):
            with open(slide, encoding="utf-8") as f:
                body = f.read()
            for node in ("Clear0", "Line0Twin"):
                self.assertIn('[node name="%s"' % node, body)
            # the ROM cycles 46 bitmaps (0x2d + 1): the loop is whole cycles, not the 246-frame recording
            self.assertEqual(46, body.count('{"duration"'))

    def test_dynamic_slides_use_rom_fonts(self):
        path = os.path.join(ROOT, "game", "tron", "media_data.json")
        if not os.path.exists(path):
            self.skipTest("media data not generated (scripts/gen_media.py)")
        deffs = json.load(open(path, encoding="utf-8"))["deffs"]
        dynamic = {d: i for d, i in deffs.items() if i["text"] and i["source"] != "reference"}
        self.assertGreater(len(dynamic), 70)
        for d, info in dynamic.items():
            self.assertTrue(any(f is not None for f in info["fonts"]), d)
            slide = effect_scene(info["slide"])
            if os.path.exists(slide):
                with open(slide, encoding="utf-8") as f:
                    body = f.read()
                self.assertIn("res://tron/rom_text.gd", body, d)
                self.assertNotIn("font_sizes/font_size", body, d)
        with open(effect_scene("deff_019"), encoding="utf-8") as f:
            body = f.read()
        for node in ("Credits", "Replay", "P1", "P4", "Award", "Separator", "BarGem", "ScoreDisplay"):
            self.assertIn('[node name="%s"' % node, body)
        self.assertIn("score_lines = true", body)
