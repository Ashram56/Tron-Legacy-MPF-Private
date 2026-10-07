#!/usr/bin/env python3
"""Boot Godot + MPF with the PuP Pack, play a rules scenario and save the PuP windows every 1.5 s.

    python scripts/pup_check.py [seconds] [scenario]     (default 40 s, gem_hurryup)

Output in captures/pup/: <window>_NNNN.png for backglass, dmd and topper (when [pup] third_screen is on),
godot.log and mpf.log. Fails when a window was never drawn or Godot's PuP player did not answer MPF.
Needs the converted media (scripts/gen_pup.py). Like render_check.py, runs under Xvfb without a display.
"""
import glob
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run  # noqa: E402
import toolchain as tc  # noqa: E402

OUT = os.path.join(tc.ROOT, "captures", "pup")


def check(out=OUT):
    from PIL import Image
    errors = []
    with open(os.path.join(out, "mpf.log"), encoding="utf-8", errors="replace") as f:
        if "'pup_ready'" not in f.read():
            errors.append("MPF never got pup_ready from Godot (see captures/pup/godot.log)")
    windows = sorted({os.path.basename(p).rsplit("_", 1)[0] for p in glob.glob(os.path.join(out, "*_*.png"))})
    if not windows:
        errors.append("no PuP window captured")
    for name in windows:
        lit = 0
        for path in sorted(glob.glob(os.path.join(out, name + "_*.png"))):
            lo, hi = Image.open(path).convert("L").getextrema()
            lit += hi > 16
        print("{}: drawn in {} captures".format(name, lit))
        if not lit:
            errors.append("{} stayed black".format(name))
    return errors


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    seconds = int(argv[0]) if argv else 40
    scenario = argv[1] if len(argv) > 1 else "gem_hurryup"
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT)
    run.run("virtual", scenario=scenario, seconds=seconds,
            godot_args=["--rendering-driver", "opengl3", "--", "--pup-capture-dir=" + OUT,
                        "--pup-capture-every-ms=1500"],
            godot_log=os.path.join(OUT, "godot.log"), mpf_log=os.path.join(OUT, "mpf.log"))
    try:
        import PIL  # noqa: F401
    except ImportError:
        import subprocess
        return subprocess.call([tc.python(), os.path.abspath(__file__), "--check-only"])
    errors = check()
    for e in errors:
        print("FAIL: " + e)
    if not errors:
        print("OK: the PuP windows play")
    return 1 if errors else 0


if __name__ == "__main__":
    if sys.argv[1:] == ["--check-only"]:
        errs = check()
        print("\n".join("FAIL: " + e for e in errs) or "OK: the PuP windows play")
        sys.exit(1 if errs else 0)
    sys.exit(main())
