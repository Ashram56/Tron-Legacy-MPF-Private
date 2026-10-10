#!/usr/bin/env python3
"""The PuP Pack part of the workspace: setup.py and run.py call it, or run it on its own.

    python scripts/pup_setup.py            # pup_pack submodule, an ffmpeg with Theora, the converted media
                                           # (Windows: the native_video add-on, Linux: GDE GoZen, which
                                           # play the mp4s as they are)
    python scripts/pup_setup.py --status   # one line: is the PuP on, and if not why

Kept out of setup.py and run.py (upstream files, one-line hooks only) so upstream merges stay clean.
"""
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fsutil  # noqa: E402
import toolchain as tc  # noqa: E402

sys.path.insert(0, tc.GAME)
from tron_pup import settings  # noqa: E402


def status():
    """(on, text): whether Godot will start the PuP windows, and a line saying so or what is missing."""
    cfg = settings.load()
    if not cfg["pup"].get("enabled", False):
        return False, "PuP off ([pup] enabled=false or TRON_PUP=0): original game only"
    pack, media = settings.pack_dir(cfg), settings.media_dir(cfg)
    if not os.path.exists(os.path.join(pack, "triggers.pup")):
        return False, ("PuP off: no PuP Pack in {} (run `python scripts/setup.py`, or "
                       "`git submodule update --init pup_pack`)".format(os.path.relpath(pack, tc.ROOT)))
    if not os.path.exists(os.path.join(media, "manifest.json")):
        return False, ("PuP off: the pack's videos are not converted yet (run `python scripts/setup.py`, or "
                       "`python scripts/pup_setup.py`)")
    screens = "backglass, DMD" + (", topper" if cfg["pup"].get("third_screen", True) else "")
    music = "PuP OST music" if cfg["pup"].get("ost_music", True) else "ROM music"
    return True, "PuP on: {} windows, {}".format(screens, music)


NATIVE_SRC = os.path.join(tc.ROOT, "pup_addons", "native_video")
NATIVE_DST = os.path.join(tc.GAME, "addons", "native_video")
NATIVE_MIN_GODOT = (4, 6)           # native_video.gdextension compatibility_minimum


GOZEN_SRC = os.path.join(tc.ROOT, "pup_addons", "gde_gozen")
GOZEN_DST = os.path.join(tc.GAME, "addons", "gde_gozen")


def native_video(os_name=None):
    """True where the PuP plays the pack's mp4s with the native_video add-on (Windows and macOS, Godot 4.6+):
    Godot's own player only does Theora, so elsewhere the videos are converted (or played by GoZen, gozen()).
    TRON_NATIVE_VIDEO=0 converts them everywhere."""
    godot = tuple(int(n) for n in tc.GODOT_VERSION.split(".")[:2])
    if os.environ.get("TRON_NATIVE_VIDEO") == "0":
        return False
    return tc.host_os(os_name) in ("windows", "macos") and godot >= NATIVE_MIN_GODOT


def gozen(os_name=None, arch=None):
    """True where the PuP plays the pack's mp4s with GDE GoZen (Linux x86_64 and arm64: FFmpeg, with the Jetson's
    hardware decoder when libnvmpi is installed, see pup_addons/gde_gozen/README.md). TRON_GOZEN=0 converts
    the videos to Theora instead."""
    if os.environ.get("TRON_GOZEN", "").strip().lower() in ("0", "false", "no", "off"):
        return False
    return tc.host_os(os_name) == "linux" and tc.host_arch(arch) in ("x86_64", "arm64")


def install_native_video():
    """Copies pup_addons/native_video (the build with the gdzig heap fix, see its FIX.md) to game/addons/."""
    say("   native_video add-on -> game/addons/native_video (the pack's mp4s play without conversion)")
    fsutil.copy_tree(NATIVE_SRC, NATIVE_DST)


def install_gozen():
    """Copies pup_addons/gde_gozen (GoZen built for this repo, see its README.md) to game/addons/."""
    say("   GDE GoZen add-on -> game/addons/gde_gozen (the pack's mp4s play without conversion)")
    fsutil.copy_tree(GOZEN_SRC, GOZEN_DST)


def say(text):
    print(text, flush=True)


def ensure_ffmpeg(py):
    """Installs imageio-ffmpeg in the venv unless an ffmpeg with libtheora is there for gen_pup.py."""
    for exe in (os.environ.get("FFMPEG"), shutil.which("ffmpeg")):
        if exe and "libtheora" in subprocess.run([exe, "-hide_banner", "-encoders"], capture_output=True,
                                                 text=True).stdout:
            return
    if subprocess.run([py, "-c", "import imageio_ffmpeg"], capture_output=True).returncode:
        say("   no ffmpeg with Theora: installing imageio-ffmpeg in the venv")
        subprocess.run([py, "-m", "pip", "install", "--quiet", "imageio-ffmpeg"], check=True)


def setup(py=None, dry=False):
    py = py or tc.python()
    say("== PuP Pack (pup_pack submodule, videos converted for Godot into pup_media/)")
    cfg = settings.load()
    pack = settings.pack_dir(cfg)
    if not os.path.exists(os.path.join(pack, "triggers.pup")):
        cmd = ["git", "submodule", "update", "--init", "--depth", "1", "pup_pack"]
        say("   $ " + " ".join(cmd))
        if not dry and subprocess.run(cmd, cwd=tc.ROOT).returncode:
            say("   could not fetch the PuP Pack (private repo: your git needs access to "
                "Ashram56/Tron-LE-PuP-Pack). The game runs without the PuP.")
            return 1
    if dry:
        return 0
    ensure_ffmpeg(py)
    native = native_video() or gozen()
    if native_video():
        install_native_video()
    elif gozen():
        install_gozen()
    else:
        for addon in (GOZEN_DST, NATIVE_DST):   # a loaded add-on would play the mp4s instead of the conversions
            if os.path.isdir(addon):
                fsutil.remove_dir(addon)
        say("   converting the pack's videos (the first time takes a while; later runs only redo changed files)")
    code = subprocess.run([py, os.path.join(tc.ROOT, "scripts", "gen_pup.py")] + (["--native"] if native else []),
                          cwd=tc.ROOT).returncode
    say("   " + status()[1])
    return code


if __name__ == "__main__":
    if sys.argv[1:] == ["--status"]:
        on, text = status()
        say(text)
        sys.exit(0 if on else 1)
    sys.exit(setup())
