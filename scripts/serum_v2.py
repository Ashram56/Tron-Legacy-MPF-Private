#!/usr/bin/env python3
"""The Serum v2 colourisation's 256x64 frames of every effect, exported once with libserum (scripts/serum_lib.py)
into serum/trn_174h_v2.zip, which the colour build (scripts/dmd_color.py) reads: so setup needs no libserum.

serum/trn_174h.cROMc is libserum's compiled form of a Serum v2 colourisation: besides colours for the ROM's
128x32 frames it holds new 256x64 art (the film clips in true HD). Only libserum reads it, so its frames are
exported here, effect by effect, as the game shows them: each effect's frames colourised in order from a fresh
load (libserum keeps state between frames: sprites, the last frame found), then its emulator capture's frames
(reference_capture.gif, "deff_NNN/capNNNN"): the colourisation knows the ROM's screens with their text and
status panel, which the effect's own frames leave to the live display.

    .venv/bin/python scripts/serum_v2.py export      # needs libserum (serum_lib.py build, or TRON_LIBSERUM)
    .venv/bin/python scripts/serum_v2.py info        # what the zip holds

Run export again after the effect frames change (a new asset package, frame_text): the build ignores an
exported frame whose 128x32 frame is no longer the one it was made from (the sha in index.json).
"""
import functools
import glob
import hashlib
import io
import json
import os
import sys
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
EXPORT = os.path.join(ROOT, "serum", "trn_174h_v2.zip")
MEDIA = os.path.join(ROOT, "game", "media", "dmd")
W, H = 256, 64


def shades_key(shades):
    """The key of a 128x32 frame of shades (bytes) in index.json."""
    return hashlib.sha1(bytes(shades)).hexdigest()[:16]


def export(media=MEDIA, out=EXPORT, cromc=None):
    import serum
    import serum_lib
    from PIL import Image, ImageSequence
    cromc = cromc or serum_lib.CROMC
    import dmd_color
    folders = sorted(d for d in glob.glob(os.path.join(media, "deff_*")) if glob.glob(os.path.join(d, "f*.png")))
    index, n = {}, 0
    tmp = out + ".tmp"
    flags = serum_lib.FLAG_REQUEST_32P_FRAMES | serum_lib.FLAG_REQUEST_64P_FRAMES
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as z:
        for folder in folders:
            deff = os.path.basename(folder)
            frames = [(os.path.basename(p), Image.open(p)) for p in sorted(glob.glob(os.path.join(folder, "f*.png")))]
            cap = dmd_color.capture_path(int(deff.split("_")[1]))
            caps = [("cap%04d" % k, f.convert("RGBA")) for k, f in
                    enumerate(ImageSequence.Iterator(Image.open(cap)))] if cap else []
            done = {}
            for run in (frames, caps):          # the effect's frames, then its emulator capture: each from a load
                ls = serum_lib.LibSerum(cromc, flags=flags)
                if ls.s.SerumVersion != 2:
                    raise SystemExit("%s is not a Serum v2 colourisation" % cromc)
                for fname, img in run:
                    sh = serum.shades(img)
                    fid, _, rgb64 = ls.colorize_v2(sh)
                    if rgb64 is None:
                        continue
                    digest = hashlib.sha1(rgb64).hexdigest()[:16]
                    if digest not in done:      # the same picture once per effect
                        buf = io.BytesIO()
                        Image.frombytes("RGB", (W, H), rgb64).save(buf, "PNG", compress_level=9)
                        done[digest] = "%s/%s.png" % (deff, digest)
                        z.writestr(done[digest], buf.getvalue())
                    index["%s/%s" % (deff, fname)] = {"sha": shades_key(sh), "id": fid, "png": done[digest]}
                    n += 1
                ls.close()
        z.writestr("index.json", json.dumps(index, sort_keys=True, indent=0))
    os.replace(tmp, out)
    return n, len(folders)


@functools.lru_cache(maxsize=2)
def load(path=EXPORT):
    """{"deff_NNN/fNNN.png": {"sha", "id", "png"}} and the open zip, or ({}, None) without the export."""
    if not os.path.exists(path):
        return {}, None
    z = zipfile.ZipFile(path)
    return json.loads(z.read("index.json")), z


def picture(z, entry):
    """The 256x64 RGB picture (PIL) of an index entry."""
    from PIL import Image
    return Image.open(io.BytesIO(z.read(entry["png"]))).convert("RGB")


def main(argv):
    if argv[:1] == ["export"]:
        n, folders = export()
        print("%d frames of %d effects -> %s (%.1f MB)" % (n, folders, EXPORT, os.path.getsize(EXPORT) / 1e6))
        return 0
    if argv[:1] == ["info"]:
        index, z = load()
        effects = {k.split("/")[0] for k in index}
        print("%d frames of %d effects, %d pictures" % (len(index), len(effects), len({v["png"] for v in index.values()})))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
