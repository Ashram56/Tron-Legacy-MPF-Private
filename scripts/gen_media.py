#!/usr/bin/env python3
"""Build the Godot (GMC) media of the game from the asset package.

Generated (all git-ignored, rebuilt by scripts/setup.py):
- game/sounds/<track>/snd_XXXX.wav    every ROM sample (GMC finds sounds by file name)
- game/media/dmd/deff_NNN/fNNN.png    the frames of each display effect
- game/slides/deffs/deff_NNN.tscn     one GMC slide per display effect (AnimatedSprite2D with the
                                      ROM frame timing, plus text labels for effects with values)
- game/tron/media_data.json           sound pools and slide facts for tron/media_bridge.py
- game/fonts/                         the ROM fonts (scripts/gen_fonts.py), and their HD twins in fonts/hd/
- game/media/dmd_hd/deff_NNN/*.png    the same frames and letter sprites upscaled FRAME_SCALE times
                                      (scripts/dmd_hd.py) for the HD display mode (game/tools/dmd_mode.gd);
                                      cached by content in .cache/dmd_hd/, so a rebuild redoes only new art

Display effects whose ROM text has no values ("BALL SAVED / KEEP SHOOTING") use the emulator's
reference capture, which includes the ROM fonts. Effects that print values (scores, counts) use the
graphics layer and draw each text line with tron/rom_text.gd: the ROM font, position and alignment of
the deff's draw call in the decompiled code (scripts/rom_layout.py). Over the bitmaps, the black boxes
the deff clears before its text (rom_layout.effect_fills); a looping background repeats whole bitmap
cycles (loop_period). Effects that draw target letters by state (LETTER_DEFFS) get one sprite per
letter and state, driven by tron/letter_panel.gd from the rules' event args.

Usage: .venv/bin/python scripts/gen_media.py [--only-data] [--no-hd]
"""
import csv
import glob
import hashlib
import json
import os
import re
import shutil
import sys

import fsutil  # Windows/OneDrive-safe folder wipes

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PKG = os.path.join(ROOT, "assets", "mpf_package")
GAME = os.path.join(ROOT, "game")
DMD_COLOR = "Color(1, 0.45, 0.05, 1)"
# The score display and the other effects that show live values are drawn from text
TEXT_ONLY = {19, 25, 26, 33, 38, 40}
# Captured effects whose code draws the status panel (deff_draw_status_panel) but whose own art covers its
# columns in the capture: their capture is shown whole (the others get the live panel over columns 0-40)
CAPTURE_PANEL_KEPT = {85, 112}
PANEL_WIDTH = 41
TICK_MS = 15.41      # ROM tick as the captures run (rom_layout.TICK_MS)
# Effects that draw the four letters of a target bank, one bitmap per letter and state
# (deff_091_zuse_collect 0x01033b3c, deff_092_zuse_more 0x01033fbc, deff_107_collect 0x0102c870):
# a collected letter is the solid image (tables 0x040d704c / 0x040d3ca8), a letter still to get the
# hollow one (0x040d7050 / 0x040d3cac) drawn with palette slot 15 at level 2, the letter just hit
# blinks solid. Images: rom_images_all.zip, solid C E L N O R S T U Z = 2603-2612, hollow = +10.
# Positions (tables 0x040d7044/48, 0x040d3ca0/a4, not in the package): x 42 + 21 * i, y 5, where the
# hollow/solid images match the deffs' graphics frames dot for dot. Event args (tron/features): the
# collected letters `lit`, the new one `new` (bit 0 = first letter). Frame = `ticks` ROM ticks; the new
# letter shows on frames where (frame >> shift) & 1, and on every frame after `solid_after`.
# all_new: every letter blinks solid (deff 92: a set completed).
LETTER_IMAGE0, LETTER_CHARS = 2603, "CELNORSTUZ"   # the solid images' letters (metadata/letter)
ZUSE = (2612, 2611, 2609, 2604)
TRON = (2610, 2608, 2607, 2606)
# deff 94 (deff_094_zfs_intro 0x01032510): the solid letters at y 1 (x as above: matched on the capture)
# on frames where frame & 2, 24 frames of 4 ticks, then the ALL TARGETS / SCORE screen (rom_layout).
LETTER_DEFFS = {94: {"images": ZUSE, "all_new": True, "ticks": 4, "shift": 1, "solid_after": 10 ** 6, "y": 1,
                     "hide_after_frame": 24},
                91: {"images": ZUSE, "lit": "lit", "new": "new", "ticks": 4, "shift": 0, "solid_after": 13},
                92: {"images": ZUSE, "all_new": True, "ticks": 3, "shift": 1, "solid_after": 21},
                107: {"images": TRON, "lit": "old", "new": "new", "ticks": 3, "shift": 1, "solid_after": 21}}
LETTER_X, LETTER_DX, LETTER_Y, UNLIT_LEVEL = 42, 21, 5, 2
# deff 105, the Flynn's Arcade award reel (deff_105_arcade_award 0x0100e8bc): drawn by tron/arcade_reel.gd
# from the cabinet and award icon images of the package (parts/index.json: cabinets 0x5c5-0x5c8, icons
# of table 0x040d29a0) and the rules' choices (tron/features/arcade.py Arcade.reel). The reference capture
# is one run whose award id was 0: it showed an empty cabinet, whatever the award.
ARCADE_DEFF = 105
ARCADE_ARGS = ["award", "cab0", "cab1", "cab2", "icon0", "icon1", "icon2", "slot", "scroll", "blink"]
ARCADE_FRAME_MS = 3 * 16.26          # a reel frame is 3 ROM ticks (os_layer.TICK)
# Text the event map's rom_text lacks: lines printed from a table or from the deff's argument.
# deff 114 (0x01026c70): SEA OF / SIMULATION and the current stage's two messages (stage table
# 0x040d37d8 + 0x18: "SHOOT" / item); deff 115 (0x010270a4): the skipped stage's messages 0x65d + 2k,
# 0x65e + 2k (item / "BONUS") and the points paid; the stage deffs 116-124 (FUN_01027374 /
# FUN_01027478): the points.
# deffs 55, 60: every screen's lines (rom_layout.SCREENS); deff 60 prints the points on either screen's row.
ROM_TEXT = {114: "SEA OF / SIMULATION / %s / %s", 115: "%s / %s / %,02lu",
            55: "MULTIBALL + E.B. / ARE LIT / EXTRA BALL / IS LIT / %u MORE TO / LIGHT MULTIBALL / LIGHT EX. BALL"
                " / LIGHT M.B. + E.B. / MULTIBALL / IS LIT",
            60: "%,02lu / BALL ADDED / %,02lu / %u MORE FOR / ADD-A-BALL",
            # deff 138 (0x01003c30): the named combo's message (table entry + 8) between points and jackpot
            138: "%u / WAY / COMBO / %,02lu / %s / JACKPOT=%,02lu",
            # deff 47 (0x01007f34): each dmb_phase's lines (rom_layout.SCREENS), with the jackpot messages
            # 0x574 / 0x577 the code picks into a variable
            47: "DISC MULTIBALL / %d / SHOOT SPINNING DISC / JACKPOT=%,02lu / %d / SHOOT RECOGNIZER"
                " / RECOGNIZER=%,02lu / SHOOT SPINNING DISC / SUPER=%,02lu",
            # deff 65 (0x0101de30): the two message pairs of table 0x040d3278, SUPER=, and the double
            # window's screen (seconds, ALL JACKPOTS / DOUBLED)
            65: "QUORRA MULTIBALL / SHOOT LEFT INNER LOOP / FOR JACKPOT / SHOOT RIGHT INNER LOOP"
                " / FOR SUPER JACKPOT / SUPER=%,02lu / %d / ALL JACKPOTS / DOUBLED",
            # deffs 68 / 69 (0x0101e320 / 0x0101e654): the DOUBLE screen (argument 2, the double window) and the
            # plain JACKPOT / SUPER JACKPOT screen, each with its own value row
            68: "DOUBLE / JACKPOT / %,02lu / JACKPOT / %,02lu",
            69: "DOUBLE / SUPER JACKPOT / %,02lu / SUPER / JACKPOT / %,02lu",
            # deff 141 (0x0102ffa0): each pm_phase's lines, with SUPER= (0x6bd / 0x6c0, picked into msg_id)
            141: "PORTAL MULTIBALL / NEXT SHOT=%,02lu / SUPER=%,02lu / SUPER JACKPOT LIT / SHOOT DISC"
                 " / SUPER=%,02lu / ALL SHOTS=%,02lu",
            **{d: "%,02lu" for d in range(116, 125)}}


def load_yaml(path):
    from ruamel.yaml import YAML
    with open(path, encoding="utf-8") as f:
        return YAML(typ="safe").load(f)


# ---------------------------------------------------------------------- sounds

def build_sounds(only_data):
    cfg = load_yaml(os.path.join(PKG, "config", "sounds.yaml"))
    sounds = cfg["sounds"]
    if not only_data:
        for name, s in sounds.items():
            track = s.get("track", "sfx")
            src = glob.glob(os.path.join(PKG, "media", "sounds", "*", s["file"]))
            if not src:
                continue
            dst_dir = os.path.join(GAME, "sounds", track)
            os.makedirs(dst_dir, exist_ok=True)
            dst = os.path.join(dst_dir, name + ".wav")
            if not os.path.exists(dst) or os.path.getsize(dst) != os.path.getsize(src[0]):
                shutil.copyfile(src[0], dst)
    pools = {}
    for name, p in cfg.get("sound_pools", {}).items():
        members = p["sounds"]
        if isinstance(members, str):
            members = [m.strip() for m in members.split(",")]
        members = [m.split("|")[0].strip() for m in members if m.split("|")[0].strip() in sounds]
        if not members:
            continue
        call = int(name.split("_")[1], 16)
        pools[call] = {"type": p.get("type", "random"), "samples": members,
                       "track": sounds[members[0]].get("track", "sfx")}
    return pools


# ---------------------------------------------------------------------- display effects

def gif_frames(path):
    from PIL import Image, ImageSequence
    img = Image.open(path)
    out = []
    for frame in ImageSequence.Iterator(img):
        out.append((frame.convert("RGBA"), int(frame.info.get("duration", 49)) or 49))
    return out


def png_frames(folder):
    from PIL import Image
    timing = json.load(open(os.path.join(folder, "timing.json"), encoding="utf-8"))
    out = []
    for f in timing.get("graphics_frames", []):
        path = os.path.join(folder, f["file"])
        if os.path.exists(path):
            out.append((Image.open(path).convert("RGBA"), max(1, int(f["duration_ms"]))))
    return out


def text_lines(rom_text):
    return [t.strip() for t in rom_text.split(" / ")] if rom_text else []


def text_node(i, lay, name=None, var=None):
    """A tron/rom_text.gd label for text line i (lay from rom_layout.line_layouts); with a twin, a second
    label with the same value at the twin's x and flags (the ROM draws the line twice)."""
    out = []
    if lay.get("twin"):
        out += text_node(i, dict({k: v for k, v in lay.items() if k not in ("twin", "alt_when_empty")},
                                 **lay["twin"]), (name or "Line%d" % i) + "Twin", var or "line%d" % i)
    out += ['', '[node name="{}" type="Label" parent="."]'.format(name or "Line%d" % i), 'layout_mode = 0',
           'theme_override_colors/font_color = {}'.format(DMD_COLOR),
           'script = ExtResource("text")', 'variable_type = 1', 'variable_name = "{}"'.format(var or "line%d" % i),
           'rom_font = {}'.format(lay["font"]), 'rom_x = {}'.format(lay["x"]),
           'rom_y = {}'.format(lay["y"]), 'rom_flags = {}'.format(lay["flags"])]
    if "fit_fonts" in lay:
        out += ['fit_fonts = PackedInt32Array({})'.format(", ".join(map(str, lay["fit_fonts"]))),
                'fit_ys = PackedInt32Array({})'.format(", ".join(map(str, lay["fit_ys"]))),
                'fit_width = {}'.format(lay["fit_width"])]
    if "alt_when_empty" in lay:
        out += ['alt_x = {}'.format(lay["alt_x"]), 'alt_y = {}'.format(lay["alt_y"]),
                'alt_when_empty = "{}"'.format(lay["alt_when_empty"])]
    if lay.get("screens"):
        out.append('screens = PackedInt32Array({})'.format(", ".join(map(str, lay["screens"]))))
    for key in ("show_after_ms", "hide_after_ms", "step_ms", "blink_ms", "cycle_ms", "cycle_on_ms",
                "cycle_offset_ms"):
        if lay.get(key):
            out.append('{} = {}'.format(key, lay[key]))
    if lay.get("blink_dark"):
        out.append('blink_dark = true')
    if lay.get("level_steps"):
        out.append('level_steps = PackedInt32Array({})'.format(", ".join(map(str, lay["level_steps"]))))
    return out


# the root script of an effect's node scene (media/dmd/<name>/nodes.tscn), shown inside its GMC slide
NODES_SLIDE = "res://addons/mpf-gmc/classes/mpf_slide.gd"
TEXT_KEYS = ("fit_fonts", "fit_ys", "fit_width", "alt_x", "alt_y", "alt_when_empty", "screens", "show_after_ms",
             "hide_after_ms", "step_ms", "blink_ms", "cycle_ms", "cycle_on_ms", "cycle_offset_ms", "blink_dark",
             "level_steps")


def text_items(i, lay, name=None, var=None):
    """The effect data's items (tron/dmd_effect.gd) of text line i: as text_node, the twin first."""
    out = []
    if lay.get("twin"):
        out += text_items(i, dict({k: v for k, v in lay.items() if k not in ("twin", "alt_when_empty")},
                                  **lay["twin"]), (name or "Line%d" % i) + "Twin", var or "line%d" % i)
    item = {"type": "text", "name": name or "Line%d" % i, "var": var or "line%d" % i, "font": lay["font"],
            "x": lay["x"], "y": lay["y"], "flags": lay["flags"]}
    item.update({k: lay[k] for k in TEXT_KEYS if lay.get(k)})
    return out + [item]


def rect_item(name, x, y, w, h, level):
    return {"type": "rect", "name": name, "x": x, "y": y, "w": w, "h": h, "level": level, "color": level_rgb(level)}


def level_rgb(level):
    """level_color's numbers (as the scenes round them, so both draw the same dots)."""
    r, g, b = (float(v) for v in DMD_COLOR[6:-4].split(", "))
    return [float("{:.4g}".format(c * level / 15)) for c in (r, g, b)]


def level_color(level):
    """DMD_COLOR at palette level 0-15 (the slide tint keeps the level in the red channel)."""
    r, g, b = (float(v) for v in DMD_COLOR[6:-4].split(", "))
    return "Color({:.4g}, {:.4g}, {:.4g}, 1)".format(r * level / 15, g * level / 15, b * level / 15)


def rect_node(name, x, y, w, h, level):
    return ['', '[node name="{}" type="ColorRect" parent="."]'.format(name), 'layout_mode = 0',
            'offset_left = {}.0'.format(x), 'offset_top = {}.0'.format(y), 'offset_right = {}.0'.format(x + w),
            'offset_bottom = {}.0'.format(y + h), 'color = {}'.format(level_color(level))]


def score_display_nodes(score_lines=True, match=False):
    """deff 19 beyond its two text lines (ROM deff_019 0x01023a98, deff_draw_status_panel 0x010230ec):
    credits and replay lines (font 0, row 30), player scores and last points in the status panel (font 0
    right-aligned at x 38), the panel's separator (x 40) and dashes (row 31) at level 1, the timer bars
    at level 15, and tron/score_display.gd driving rotation, blink, dimming and bars."""
    import rom_layout
    out = []
    for name, var, x, y, flags in rom_layout.SCORE_PANEL:
        if score_lines or name not in ("Credits", "Replay"):
            out += text_node(0, {"font": 0, "x": x, "y": y, "flags": flags}, name, var)
    out += rect_node("Separator", 40, 0, 1, 32, 1)
    for k, (name, x) in enumerate((("BarDs", 4), ("BarBumpers", 16), ("BarSpinners", 28))):
        out += rect_node("Dash%d" % k, x, 31, 10, 1, 1)
        out += rect_node(name, x, 31, 0, 1, 15)
    for name in ("BarZfs", "BarClu", "BarGem"):
        out += rect_node(name, 40, 0, 1, 0, 15)
    out += ['', '[node name="ScoreDisplay" type="Node" parent="."]', 'script = ExtResource("score")']
    if score_lines:
        out.append('score_lines = true')
    if match:
        out.append('match_panel = true')
    return out


def score_display_items(score_lines=True, match=False):
    """The effect data's items of score_display_nodes (same names, same order)."""
    import rom_layout
    out = []
    for name, var, x, y, flags in rom_layout.SCORE_PANEL:
        if score_lines or name not in ("Credits", "Replay"):
            out += text_items(0, {"font": 0, "x": x, "y": y, "flags": flags}, name, var)
    out.append(rect_item("Separator", 40, 0, 1, 32, 1))
    for k, (name, x) in enumerate((("BarDs", 4), ("BarBumpers", 16), ("BarSpinners", 28))):
        out += [rect_item("Dash%d" % k, x, 31, 10, 1, 1), rect_item(name, x, 31, 0, 1, 15)]
    for name in ("BarZfs", "BarClu", "BarGem"):
        out.append(rect_item(name, 40, 0, 1, 0, 15))
    return out + [{"type": "panel", "score_lines": score_lines, "match": match}]


def letter_nodes(deff_id, spec, folder_rel):
    """ext_resources and nodes of a letter effect (LETTER_DEFFS): Solid0-3 and Hollow0-3 sprites and
    tron/letter_panel.gd showing them from the event args."""
    import io
    import zipfile
    from PIL import Image
    z = zipfile.ZipFile(os.path.join(PKG, "media", "rom_images_all.zip"))
    ext, nodes = ['[ext_resource type="Script" path="res://tron/letter_panel.gd" id="letters"]'], []
    sprites = []
    for i, solid in enumerate(spec["images"]):
        for kind, image, level in (("Solid", solid, 15), ("Hollow", solid + 10, UNLIT_LEVEL)):
            fname = "{}{}.png".format(kind.lower(), i)
            Image.open(io.BytesIO(z.read("%04d.png" % image))).convert("RGBA").save(
                os.path.join(GAME, folder_rel, fname))
            rid = "{}{}".format(kind.lower(), i)
            ext.append('[ext_resource type="Texture2D" path="res://{}/{}" id="{}"]'.format(folder_rel, fname, rid))
            nodes += ['', '[node name="{}{}" type="Sprite2D" parent="."]'.format(kind, i),
                      'modulate = {}'.format(level_color(level)), 'texture = ExtResource("{}")'.format(rid),
                      'centered = false',
                      'position = Vector2({}, {})'.format(LETTER_X + LETTER_DX * i, spec.get("y", LETTER_Y)),
                      'metadata/letter = "{}"'.format(LETTER_CHARS[solid - LETTER_IMAGE0])]
            sprites.append({"name": "{}{}".format(kind, i), "pic": "res://{}/{}".format(folder_rel, fname),
                            "x": LETTER_X + LETTER_DX * i, "y": spec.get("y", LETTER_Y), "level": level,
                            "color": level_rgb(level),
                            "letter": LETTER_CHARS[solid - LETTER_IMAGE0]})
    nodes += ['', '[node name="LetterPanel" type="Node" parent="."]', 'script = ExtResource("letters")',
              'lit_key = "{}"'.format(spec.get("lit", "")), 'new_key = "{}"'.format(spec.get("new", "")),
              'all_new = {}'.format("true" if spec.get("all_new") else "false"),
              'frame_ms = {}'.format(round(spec["ticks"] * TICK_MS, 2)), 'blink_shift = {}'.format(spec["shift"]),
              'solid_after = {}'.format(spec["solid_after"]),
              'hide_after_ms = {}'.format(round(spec.get("hide_after_frame", 0) * spec["ticks"] * TICK_MS))]
    item = {"type": "letters", "sprites": sprites, "lit_key": spec.get("lit", ""), "new_key": spec.get("new", ""),
            "all_new": bool(spec.get("all_new")), "frame_ms": round(spec["ticks"] * TICK_MS, 2),
            "blink_shift": spec["shift"], "solid_after": spec["solid_after"],
            "hide_after_ms": round(spec.get("hide_after_frame", 0) * spec["ticks"] * TICK_MS)}
    return ext, nodes, item


def arcade_slide(folder, folder_rel, panel):
    """deff 105: the reel sprites and tron/arcade_reel.gd, a black panel area left of x 41 (deff_status_frames
    0x010241a0 copies the effect from x 41 on), the status panel."""
    from PIL import Image
    index = json.load(open(os.path.join(folder, "parts", "index.json"), encoding="utf-8"))
    ext = ['[ext_resource type="Script" path="res://tron/arcade_reel.gd" id="reel"]']
    groups = {"cabinets": [], "icons_a": [], "icons_b": []}
    pics = {"cabinets": [], "icons_a": [], "icons_b": []}
    files = [("cabinets", "cab%d" % i, c["file"]) for i, c in enumerate(index["cabinets"])]
    for a in sorted(index["awards"], key=lambda a: a["award_id"]):
        files += [("icons_a", "a%d" % a["award_id"], a["file_a"]), ("icons_b", "b%d" % a["award_id"], a["file_b"])]
    for group, rid, fname in files:
        Image.open(os.path.join(folder, "parts", fname)).convert("RGBA").save(os.path.join(GAME, folder_rel, fname))
        ext.append('[ext_resource type="Texture2D" path="res://{}/{}" id="{}"]'.format(folder_rel, fname, rid))
        groups[group].append('ExtResource("{}")'.format(rid))
        pics[group].append("res://{}/{}".format(folder_rel, fname))
    name = "deff_{:03d}".format(ARCADE_DEFF)
    parts = ['[gd_scene load_steps={} format=3]'.format(len(ext) + 3), '',
             '[ext_resource type="Script" path="{}" id="slide"]'.format(NODES_SLIDE),
             '[ext_resource type="Script" path="res://tron/rom_text.gd" id="text"]',
             '[ext_resource type="Script" path="res://tron/score_display.gd" id="score"]'] + ext
    parts += ['', '[node name="{}" type="Control"]'.format(name), 'layout_mode = 3', 'anchors_preset = 0',
              'offset_right = 128.0', 'offset_bottom = 32.0', 'script = ExtResource("slide")', '',
              '[node name="Background" type="ColorRect" parent="."]', 'layout_mode = 0',
              'offset_right = 128.0', 'offset_bottom = 32.0', 'color = Color(0, 0, 0, 1)', '',
              '[node name="Reel" type="Node2D" parent="."]', 'modulate = {}'.format(DMD_COLOR),
              'script = ExtResource("reel")']
    for group, refs in groups.items():
        parts.append('{} = Array[Texture2D]([{}])'.format(group, ", ".join(refs)))
    parts.append('frame_ms = {}'.format(round(ARCADE_FRAME_MS, 2)))
    parts += rect_node("PanelClear", 0, 0, 41, 32, 0)
    parts += score_display_nodes(False, panel == "match")
    items = [rect_item("Background", 0, 0, 128, 32, 0),
             dict({"type": "arcade", "name": "Reel", "frame_ms": round(ARCADE_FRAME_MS, 2)}, **pics),
             rect_item("PanelClear", 0, 0, 41, 32, 0)] + score_display_items(False, panel == "match")
    write_effect(name, folder_rel, parts, items)
    return name


def write_effect(name, folder_rel, scene, items):
    """A display effect's outputs: its data (media/dmd/<name>/effect.json, drawn by tron/dmd_screen.gd), its node
    scene (media/dmd/<name>/nodes.tscn, shown instead with tron/dmd/renderer="nodes") and its GMC slide
    (slides/deffs/<name>.tscn, tron/dmd_effect_slide.gd: draws the data, or shows the node scene or a custom scene
    res://dmd_custom/<name>.tscn)."""
    with open(os.path.join(GAME, folder_rel, "nodes.tscn"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(scene) + "\n")
    with open(os.path.join(GAME, folder_rel, "effect.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump({"name": name, "items": items}, f, indent=1)
        f.write("\n")
    proxy = ['[gd_scene load_steps=2 format=3]', '',
             '[ext_resource type="Script" path="res://tron/dmd_effect_slide.gd" id="slide"]', '',
             '[node name="{}" type="Control"]'.format(name), 'layout_mode = 3', 'anchors_preset = 0',
             'offset_right = 128.0', 'offset_bottom = 32.0', 'script = ExtResource("slide")',
             'effect = "res://{}/effect.json"'.format(folder_rel)]
    with open(os.path.join(GAME, "slides", "deffs", name + ".tscn"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(proxy) + "\n")


def loop_period(frames):
    """The shortest run of frames that repeats through the whole recording (the ROM's bitmap cycle), or
    None. The recordings stop at the capture timeout, mid-cycle: looping the whole recording would jump
    back to the first bitmap from the middle of the cycle."""
    h = [hashlib.md5(img.tobytes()).hexdigest() for img, _ in frames]
    n = len(h)
    return next((p for p in range(1, n // 2 + 1) if all(h[i] == h[i + p] for i in range(n - p))), None)


# Pictures shared between effects in their data: (md5 of the 128x32 frame, recorded) -> the first effect's file. The
# Sea of Simulation stages (deffs 116-124) draw the same animation: an effect's data names the first copy, so the copies
# are never loaded (11% of the frames). Recorded frames (source "reference") share only with recorded frames: their HD
# twins have their text cleared (scripts/frame_text.py).
SHARED = {}


def write_slide(deff_id, frames, layouts, loop, folder_rel, panel=False, fills=(), letters=None, recorded=False):
    name = "deff_{:03d}".format(deff_id)
    ext, entries = [], []
    seen = {}
    files, order = {}, []           # the effect data's frames: picture file and duration
    for i, (img, ms) in enumerate(frames):
        digest = hashlib.md5(img.tobytes()).hexdigest()
        if digest not in seen:
            fname = "f{:03d}.png".format(len(seen))
            files[digest] = SHARED.setdefault((digest, recorded), "res://{}/{}".format(folder_rel, fname))
            img.save(os.path.join(GAME, folder_rel, fname))
            seen[digest] = "t{}".format(len(seen))
            ext.append('[ext_resource type="Texture2D" path="res://{}/{}" id="{}"]'.format(
                folder_rel, fname, seen[digest]))
        entries.append('{{"duration": {:.1f}, "texture": ExtResource("{}")}}'.format(ms, seen[digest]))
        order.append((digest, ms))
    letter_ext, letter_nodes_, letter_item = letter_nodes(deff_id, letters, folder_rel) if letters else ([], [], None)
    parts = ['[gd_scene load_steps={} format=3]'.format(len(ext) + len(letter_ext) + (3 if frames else 2)), '',
             '[ext_resource type="Script" path="{}" id="slide"]'.format(NODES_SLIDE)]
    if any(layouts) or panel:
        parts.append('[ext_resource type="Script" path="res://tron/rom_text.gd" id="text"]')
    if panel:
        parts.append('[ext_resource type="Script" path="res://tron/score_display.gd" id="score"]')
    parts += ext + letter_ext
    if frames:
        parts += ['', '[sub_resource type="SpriteFrames" id="frames"]',
                  'animations = [{{"frames": [{}], "loop": {}, "name": &"default", "speed": 1000.0}}]'.format(
                      ", ".join(entries), "true" if loop else "false")]
    parts += ['', '[node name="{}" type="Control"]'.format(name), 'layout_mode = 3', 'anchors_preset = 0',
              'offset_right = 128.0', 'offset_bottom = 32.0', 'script = ExtResource("slide")', '',
              '[node name="Background" type="ColorRect" parent="."]', 'layout_mode = 0',
              'offset_right = 128.0', 'offset_bottom = 32.0', 'color = Color(0, 0, 0, 1)']
    if frames:
        parts += ['', '[node name="Anim" type="AnimatedSprite2D" parent="."]',
                  'modulate = {}'.format(DMD_COLOR), 'sprite_frames = SubResource("frames")',
                  'autoplay = "default"', 'centered = false']
    for k, (x0, y0, x1, y1) in enumerate(fills):     # black boxes the ROM clears over the bitmap
        parts += rect_node("Clear%d" % k, x0, y0, x1 - x0 + 1, y1 - y0 + 1, 0)
    parts += letter_nodes_
    for i, lay in enumerate(layouts):
        if lay:
            parts += text_node(i, lay)
    if panel:
        parts += score_display_nodes(deff_id == 19, panel == "match")
    items = [rect_item("Background", 0, 0, 128, 32, 0)]
    if frames:
        items.append({"type": "frames", "name": "Anim", "loop": bool(loop),
                      "frames": [[files[k], round(ms, 1)] for k, ms in order]})
    items += [rect_item("Clear%d" % k, x0, y0, x1 - x0 + 1, y1 - y0 + 1, 0) for k, (x0, y0, x1, y1) in enumerate(fills)]
    if letter_item:
        items.append(letter_item)
    for i, lay in enumerate(layouts):
        if lay:
            items += text_items(i, lay)
    if panel:
        items += score_display_items(deff_id == 19, panel == "match")
    write_effect(name, folder_rel, parts, items)
    return name


def build_deffs(only_data):
    import rom_layout
    rows = {int(r["deff"]): r for r in csv.DictReader(open(os.path.join(PKG, "event_map.csv"), encoding="utf-8"))}
    fonts = json.load(open(os.path.join(GAME, "fonts", "fonts.json"), encoding="utf-8"))["fonts"]
    calls = rom_layout.deff_calls()
    panels = rom_layout.status_panel_deffs()
    fills = rom_layout.effect_fills()
    out = {}
    os.makedirs(os.path.join(GAME, "slides", "deffs"), exist_ok=True)
    for folder in sorted(glob.glob(os.path.join(PKG, "media", "dmd", "deff_*"))):
        deff_id = int(os.path.basename(folder).split("_")[1])
        row = rows.get(deff_id, {})
        rom_text = ROM_TEXT.get(deff_id, row.get("rom_text", ""))
        dynamic = "%" in rom_text or deff_id in TEXT_ONLY
        loop = row.get("background_loop") == "yes"
        ref = os.path.join(folder, "reference_capture.gif")
        has_graphics = os.path.isdir(os.path.join(folder, "frames"))
        letters = LETTER_DEFFS.get(deff_id)
        if deff_id == ARCADE_DEFF:     # drawn from the rules' award, not the capture's (award id 0)
            source, lines = "arcade", []
        elif letters:                    # letters drawn from the rules' state, not the capture's
            source, lines = "letters", text_lines(rom_text)
        elif dynamic or not os.path.exists(ref):
            source, lines = ("graphics" if has_graphics else "none"), text_lines(rom_text)
        else:
            source, lines = "reference", []
        layouts = rom_layout.line_layouts(deff_id, lines, fonts, calls.get(deff_id, []))
        # a capture shows the status panel of the moment it was recorded (score 00): the live panel is drawn
        # over its columns 0-40 instead, except where the effect itself covers them (deffs 85, 112)
        panel = panels.get(deff_id) if source != "reference" or deff_id not in CAPTURE_PANEL_KEPT else None
        info = {"slide": "deff_{:03d}".format(deff_id), "source": source, "text": lines, "loop": loop,
                "panel": panel, "args": ([letters[k] for k in ("lit", "new") if k in letters] if letters else [])
                + (["screen"] if deff_id in rom_layout.SCREENS else [])
                + (ARCADE_ARGS if source == "arcade" else []),
                "fonts": [lay["font"] if lay else None for lay in layouts]}
        out[deff_id] = info
        if only_data:
            continue
        rel = "media/dmd/deff_{:03d}".format(deff_id)    # also a res:// path: "/" on every OS
        fsutil.clear_dir(os.path.join(GAME, rel))
        if source == "arcade":
            arcade_slide(folder, rel, panel)
            continue
        frames = gif_frames(ref) if source == "reference" else png_frames(folder) if source == "graphics" else []
        if source == "reference" and panel:
            from PIL import ImageDraw
            for img, _ in frames:
                ImageDraw.Draw(img).rectangle((0, 0, PANEL_WIDTH - 1, 31), fill=(0, 0, 0, 255))
        end = rom_layout.GRAPHICS_END.get(deff_id)
        if end and source == "graphics" and len(frames) >= end:  # the ROM stops drawing bitmaps at frame `end`
            from PIL import Image
            last_ms = frames[end - 1][1]
            frames = frames[:end - 1] + [(frames[end - 1][0], frames[end - 2][1]),
                                         (Image.new("RGBA", (128, 32)), max(1, last_ms - frames[end - 2][1]))]
        if loop and source == "graphics":       # loop whole bitmap cycles only
            period = loop_period(frames)
            frames = frames[:period] if period else frames
        write_slide(deff_id, frames, layouts, loop, rel, panel,
                    fills.get(deff_id, ()) if source == "graphics" else (), letters, source == "reference")
    return out


# Godot import settings for the HD effect frames: VRAM-compressed (ETC2 on ARM, S3TC/BPTC on PCs; one channel, as
# the frames are grey). An effect's frames load when its slide is created, on Godot's main thread: lossless frames
# took ~7 ms each to decompress (the 319 frames of the Light Cycle multiball intro stalled the game 2.4 s on a Jetson
# Xavier NX), VRAM-compressed ones ~1.5 ms, at half the GPU memory (docs/performance.md). Godot completes the file
# (uid, paths) on import and keeps these parameters. Letter sprites stay lossless: tron/letter_panel.gd reads them.
HD_FRAME_IMPORT = """[remap]

importer="texture"
type="CompressedTexture2D"

[params]

compress/mode=2
mipmaps/generate=false
"""


def build_hd_frames(scale=None, deffs=None):
    """game/media/dmd_hd: every picture of game/media/dmd upscaled (dmd_hd.upscale_file), same names.
    Letter sprites (solid*/hollow*) keep their transparency; effect frames are drawn over black. The
    recorded effects' frames (deffs: build_deffs, source "reference") lose their ROM-font letters, which
    the HD mode draws live (scripts/frame_text.py, media/dmd_hd/text.json); effects whose pictures are only
    rectangles (frames, blocks) lose those too, drawn as rectangles (media/dmd_hd/shapes.json).
    Effect frames get a VRAM-compressed import (HD_FRAME_IMPORT)."""
    import dmd_hd
    import frame_text
    scale = scale or dmd_hd.FRAME_SCALE
    src_root = os.path.join(GAME, "media", "dmd")
    dst_root = os.path.join(GAME, "media", "dmd_hd")
    fsutil.remove_dir(dst_root)
    fsutil.remove_dir(os.path.join(GAME, "media", "dmd_hd_color"))    # the colour frames of earlier versions
    recorded = {info["slide"] for info in (deffs or {}).values() if info["source"] == "reference"}
    frames = sorted(p for p in glob.glob(os.path.join(src_root, "deff_*", "f*.png")))
    texts = frame_text.process_files(frames, os.path.join(ROOT, ".cache", "frame_text"), recorded)
    jobs, lines, rects = [], {}, {}
    for folder in sorted(glob.glob(os.path.join(src_root, "deff_*"))):
        out = os.path.join(dst_root, os.path.basename(folder))
        os.makedirs(out, exist_ok=True)
        for src in sorted(glob.glob(os.path.join(folder, "*.png"))):
            name = os.path.basename(src)
            kind = "sprite" if name.startswith(("solid", "hollow")) else "frame"
            found, boxes, cleared = texts.get(src, ([], [], None))
            key = os.path.basename(folder) + "/" + name
            if found:
                lines[key] = found
            if boxes:
                rects[key] = boxes
            jobs.append((cleared or src, os.path.join(out, name), scale, kind, os.path.join(ROOT, ".cache", "dmd_hd")))
            if kind == "frame":
                with open(os.path.join(out, name + ".import"), "w", encoding="utf-8", newline="\n") as f:
                    f.write(HD_FRAME_IMPORT)
    with open(os.path.join(dst_root, "scale.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump({"scale": scale}, f)
    with open(os.path.join(dst_root, "text.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(lines, f, indent=0, sort_keys=True)
    with open(os.path.join(dst_root, "shapes.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(rects, f, indent=0, sort_keys=True)
    return len(dmd_hd.upscale_files(jobs))


def main():
    import gen_fonts
    only_data = "--only-data" in sys.argv
    hd = "--no-hd" not in sys.argv
    if not only_data or not os.path.exists(os.path.join(GAME, "fonts", "fonts.json")):
        gen_fonts.build(hd=hd)
    data = {"pools": build_sounds(only_data), "deffs": build_deffs(only_data)}
    if not hd and not only_data:                   # no HD media: the HD mode shows the classic DMD
        fsutil.remove_dir(os.path.join(GAME, "fonts", "hd"))
        fsutil.remove_dir(os.path.join(GAME, "media", "dmd_hd"))
    if hd and not only_data:
        print("media: {} HD pictures in game/media/dmd_hd".format(build_hd_frames(deffs=data["deffs"])), flush=True)
    with open(os.path.join(GAME, "tron", "media_data.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=0, sort_keys=True)
    print("media: {} sound pools, {} display effects".format(len(data["pools"]), len(data["deffs"])))


if __name__ == "__main__":
    main()
