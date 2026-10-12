#!/usr/bin/env python3
"""Match the PuP Pack's DMD captures (PupCapture/<n>.bmp, trigger D<n>) against the game's display effects.

    python scripts/pup/pup_captures.py            # writes docs/pup/captures.md, exits 1 if the map disagrees

In Visual Pinball, PinUP Player fires D<n> when the pixels inside the purple rectangle of capture <n> show on
PinMAME's DMD. This compares that rectangle (lit / unlit dots) with every frame the asset package recorded:
each display effect's reference capture, its animation and variants, and the ROM's library animations
(credited to the effects that use them, event_map.csv). The effects whose frames match best are what
game/tron_pup/trigger_map.yaml should map D<n> to. Re-run it when the upstream DMD animations change.
Needs Pillow (in .venv).
"""
import csv
import glob
import os
import re
import sys

from PIL import Image, ImageSequence

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # scripts/
import toolchain as tc  # noqa: E402

sys.path.insert(0, tc.GAME)
from tron_pup import engine, pupfiles, settings  # noqa: E402

PACKAGE = os.path.join(tc.ROOT, "assets", "mpf_package")
REPORT = os.path.join(tc.ROOT, "docs", "pup", "captures.md")
PURPLE = (253, 0, 253)
W, H = 128, 32


def bits(image, test):
    """The pixels of a 128x32 image that pass test(pixel), as one int (bit y*128+x)."""
    data, n = image.tobytes(), len(image.getbands())
    pixels = data if n == 1 else (tuple(data[i:i + n]) for i in range(0, len(data), n))
    value = 0
    for i, px in enumerate(pixels):
        if test(px):
            value |= 1 << i
    return value


def frames():
    """(effect ids, label, lit bits) for every recorded frame."""
    lib = {}
    with open(os.path.join(PACKAGE, "event_map.csv"), encoding="utf-8") as f:
        for row in csv.DictReader(f):
            for anim in (row["library_animations"] or "").split():
                lib.setdefault(anim, set()).add(int(row["deff"]))
    paths = (glob.glob(os.path.join(PACKAGE, "media", "dmd", "deff_*", "*.gif"))
             + glob.glob(os.path.join(PACKAGE, "media", "dmd", "deff_*", "variants", "**", "*.gif"), recursive=True)
             + glob.glob(os.path.join(PACKAGE, "media", "dmd_library", "anim_*", "animation_128x32.gif")))
    for path in sorted(paths):
        if path.endswith("_x4.gif"):
            continue
        rel = os.path.relpath(path, PACKAGE).replace(os.sep, "/")
        m = re.search(r"deff_(\d+)", rel)
        owners = {int(m.group(1))} if m else lib.get(re.search(r"(anim_\d+_img\d+)", rel).group(1), set())
        image = Image.open(path)
        if image.size != (W, H):
            continue
        for i, frame in enumerate(ImageSequence.Iterator(image)):
            yield owners, "{}#{}".format(rel, i), bits(frame.convert("L"), lambda v: v >= 9)


def capture(path):
    image = Image.open(path).convert("RGB")
    purple = bits(image, lambda px: px == PURPLE)
    xs = [i % W for i in range(W * H) if purple >> i & 1]
    ys = [i // W for i in range(W * H) if purple >> i & 1]
    if not xs:
        return None
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    mask = 0
    for y in range(y0, y1 + 1):
        mask |= ((1 << (x1 - x0 + 1)) - 1) << (y * W + x0)
    mask &= ~purple
    lit = bits(image, lambda px: px != PURPLE and px[0] >= 9)
    return (x0, y0, x1, y1), mask, lit & mask


def main():
    cfg = settings.load()
    pack = settings.pack_dir(cfg)
    captures = sorted(glob.glob(os.path.join(pack, "PupCapture", "*.bmp")),
                      key=lambda p: int(os.path.splitext(os.path.basename(p))[0]))
    if not captures:
        raise SystemExit("no captures in {}/PupCapture (git submodule update --init pup_pack)".format(pack))
    recorded = list(frames())
    mapping = engine.load_map()["dmd"]
    used = {}
    for row in pupfiles.load_triggers(pack):
        for kind, num, _ in row.terms:
            if kind == "D":
                used.setdefault(num, []).append(row.id)
    lines = ["# PuP DMD captures against the game's display effects", "",
             "Written by `scripts/pup/pup_captures.py` ({} recorded frames). D<n> fires in Visual Pinball when the "
             "pixels in the purple rectangle of `PupCapture/<n>.bmp` are on the DMD; *score* is the share of "
             "lit dots the best frame has in common with it (intersection over union). *Effects* are all the "
             "display effects with a frame within 0.5 % of the best; *map* is what "
             "`game/tron_pup/trigger_map.yaml` uses.".format(len(recorded)), "",
             "| D | rows | rectangle | score | effects | map | |", "|---|---|---|---|---|---|---|"]
    disagree = 0
    for path in captures:
        n = int(os.path.splitext(os.path.basename(path))[0])
        cap = capture(path)
        if cap is None:
            continue
        rect, mask, lit = cap
        scores = []
        for owners, label, frame in recorded:
            region = frame & mask
            union = bin(region | lit).count("1")
            scores.append(((bin(region & lit).count("1") / union) if union else 1.0, owners, label))
        best = max(s[0] for s in scores)
        floor = best - 0.005 if best >= 0.97 else best - 0.02
        effects = sorted({d for s, owners, _ in scores if s >= floor for d in owners})
        mapped = sorted({int(m.group(1)) for e in mapping.get(n, []) for m in [re.match(r"tron_deff_(\d+)", str(e))]
                         if m})
        other = [str(e) for e in mapping.get(n, []) if not str(e).startswith("tron_deff_")]
        ok = (set(mapped) <= set(effects) and mapped) or other or not used.get(n)
        disagree += 0 if ok else 1
        lines.append("| {} | {} | {} | {:.0%} | {} | {} | {} |".format(
            n, " ".join(map(str, used.get(n, []))) or "-", "{},{}-{},{}".format(*rect), best,
            " ".join(map(str, effects)) or "-", " ".join(list(map(str, mapped)) + other) or "-",
            "" if ok else "**check**"))
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("{} captures, {} to check: {}".format(len(captures), disagree, REPORT))
    return 1 if disagree else 0


if __name__ == "__main__":
    sys.exit(main())
