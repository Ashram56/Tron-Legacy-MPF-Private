#!/usr/bin/env python3
"""Install the workspace on Windows, macOS or Linux (x86_64 or arm64). Standard library only.

    python scripts/setup.py                 # everything, MPF Monitor included; safe to re-run (steps in place are skipped)
    python scripts/setup.py --no-monitor    # without MPF Monitor (mpf-monitor, Qt)
    python scripts/setup.py --vpx           # also the Visual Pinball X bridge's packages (docs/vpx.md)
    python scripts/setup.py --dry-run       # print the plan (URLs, paths) and change nothing
    python scripts/setup.py --dry-run --os windows --arch x86_64   # the plan for another host

Steps: the assets submodule; .venv/ with the pinned MPF, pillow and pytest; Godot (official build for the
host) in tools/godot/; the GMC add-on in game/addons/mpf-gmc/; the generated MPF config and media
(scripts/gen_config.py, scripts/gen_media.py, which also builds the HD DMD fonts and frames with
scripts/dmd_hd.py, and the HD colour frames with scripts/dmd_color.py); the Godot import (game/.godot/).
Versions and paths live in scripts/toolchain.py.
"""
import argparse
import io
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fsutil  # noqa: E402  (Windows/OneDrive-safe folder wipes)
import gmc_patch  # noqa: E402
import pup_setup  # noqa: E402  (PuP Pack: docs/pup.md)
import toolchain as tc  # noqa: E402


class Setup:

    def __init__(self, args):
        self.args = args
        self.os = tc.host_os(args.os)
        self.arch = tc.host_arch(args.arch)
        self.native = args.os is None and args.arch is None
        self.dry = args.dry_run or not self.native

    def say(self, text):
        print(text, flush=True)

    def run(self, cmd, **kw):
        self.say("   $ " + " ".join(cmd))
        if not self.dry:
            subprocess.run(cmd, check=True, **kw)

    # ------------------------------------------------------------------ steps

    def assets(self):
        self.say("== assets submodule")
        if os.path.isdir(os.path.join(tc.ROOT, "assets", "mpf_package")):
            self.say("   in place")
            return
        if not shutil.which("git") or not os.path.exists(os.path.join(tc.ROOT, ".git")):
            raise SystemExit("assets/ is empty: clone with --recurse-submodules, or run "
                             "`git submodule update --init --depth 1 assets`")
        self.run(["git", "submodule", "update", "--init", "--depth", "1", "assets"], cwd=tc.ROOT,
                 env=dict(os.environ, GIT_LFS_SKIP_SMUDGE="1"))

    def venv(self):
        self.say("== Python venv (.venv) with MPF {}".format(tc.MPF_VERSION))
        if sys.version_info[:2] < tc.PYTHON_MIN:
            raise SystemExit("Python {}.{}+ is needed, this is {}".format(*tc.PYTHON_MIN, sys.version.split()[0]))
        py = tc.venv_python(self.os)
        mpf = tc.venv_exe("mpf", self.os)
        self.say("   python: " + py)
        reqs = list(tc.REQUIREMENTS)
        if self.args.monitor:
            reqs += tc.MONITOR_REQUIREMENTS
        if getattr(self.args, "vpx", False):
            reqs += tc.VPX_REQUIREMENTS
        if not os.path.exists(py) or self.dry:
            # a .venv whose Python is gone (the interpreter it was made from was removed or replaced) is remade
            clear = ["--clear"] if not os.path.exists(py) and os.path.isdir(tc.venv_dir()) else []
            self.run([sys.executable, "-m", "venv"] + clear + [tc.venv_dir()])
        missing = self.dry or (not os.path.exists(mpf) or self.args.upgrade
                               or (self.args.monitor and not self.has_module(py, "mpfmonitor"))
                               or not self.has_module(py, "fontTools")
                               or (getattr(self.args, "vpx", False) and not self.has_module(py, "olefile")))
        if missing:
            self.run([py, "-m", "pip", "install", "--quiet", "--upgrade", "pip"])
            self.run([py, "-m", "pip", "install", "--quiet"] + reqs)
        else:
            self.say("   in place")
        self.run([mpf, "--version"])
        if self.args.monitor:
            self.say("== MPF Monitor's window layouts ({} files missing from its PyPI release)".format(
                len(tc.MPF_MONITOR_UI_FILES)))
            self.say("   url:  " + tc.MPF_MONITOR_UI_URL)
            if not self.dry:
                install_monitor_ui(py)

    def has_module(self, py, name):
        return subprocess.run([py, "-c", "import " + name], capture_output=True).returncode == 0

    def godot(self):
        self.say("== Godot {} ({} {})".format(tc.GODOT_VERSION, self.os, self.arch))
        exe = tc.godot_path(self.os, self.arch)
        url = tc.godot_url(self.os, self.arch)
        self.say("   url:  " + url)
        self.say("   exe:  " + exe)
        if os.environ.get("GODOT") and self.native:
            self.say("   GODOT is set: using " + os.environ["GODOT"])
            exe = os.environ["GODOT"]
        elif os.path.exists(exe) and not self.dry:
            self.say("   in place")
        elif not self.dry:
            os.makedirs(tc.godot_dir(), exist_ok=True)
            data = download(url)
            unzip(data, tc.godot_dir(), self.os)
            if self.os != "windows":
                os.chmod(exe, os.stat(exe).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        if self.os == "linux" and not self.dry and not os.environ.get("GODOT"):
            # tools/godot/godot: the short name the docs and older commands use
            link = os.path.join(tc.godot_dir(), "godot")
            if os.path.lexists(link):
                os.remove(link)
            os.symlink(os.path.relpath(exe, tc.godot_dir()), link)
        self.run([exe, "--headless", "--version"])

    def gmc(self):
        self.say("== GMC add-on {} (game/addons/mpf-gmc)".format(tc.GMC_VERSION))
        self.say("   url:  " + tc.GMC_ZIP)
        if os.path.exists(os.path.join(tc.GMC_DIR, "plugin.cfg")) and not self.dry:
            self.say("   in place")
            gmc_patch.patch()
            return
        if self.dry:
            return
        prefix = "mpf-gmc-{}/addons/mpf-gmc/".format(tc.GMC_VERSION)
        try:
            if not extract_folder(download(tc.GMC_ZIP), prefix, tc.GMC_DIR):
                raise SystemExit("no {} in {}".format(prefix, tc.GMC_ZIP))
        except (OSError, zipfile.BadZipFile) as e:
            if not shutil.which("git"):
                raise
            self.say("   zip download failed ({}), cloning with git".format(e))
            with tempfile.TemporaryDirectory() as tmp:
                subprocess.run(["git", "-c", "advice.detachedHead=false", "clone", "--quiet", "--depth", "1",
                                "--branch", "v" + tc.GMC_VERSION, tc.GMC_GIT, os.path.join(tmp, "gmc")], check=True)
                fsutil.copy_tree(os.path.join(tmp, "gmc", "addons", "mpf-gmc"), tc.GMC_DIR)
        gmc_patch.patch()

    def generate(self):
        py = tc.venv_python(self.os)
        self.say("== MPF config generated from the asset package")
        self.run([py, os.path.join(tc.ROOT, "scripts", "gen_config.py")], cwd=tc.ROOT)
        self.say("== Media (sounds, DMD frames, slides and fonts from the asset package, and their HD versions)")
        self.run([py, os.path.join(tc.ROOT, "scripts", "gen_media.py")], cwd=tc.ROOT)

    def godot_import(self):
        self.say("== Godot import (builds game/.godot/)")
        exe = os.environ.get("GODOT") if self.native and os.environ.get("GODOT") else tc.godot_path(self.os, self.arch)
        # The first import pass can report add-on icon errors; the second is clean.
        for _ in range(2):
            cmd = [exe, "--headless", "--path", tc.GAME, "--import"]
            self.say("   $ " + " ".join(cmd))
            if not self.dry:
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=900)


def refresh_media():
    """Generate the config and media again and import them into Godot (scripts/run.py, docker setup, when
    tc.media_stale() says the workspace still shows the media of older code or assets)."""
    s = Setup(argparse.Namespace(os=None, arch=None, dry_run=False, monitor=False, upgrade=False))
    s.generate()
    s.godot_import()
    tc.write_media_stamp()


def download(url):
    """The bytes at url. urllib first; curl (Windows 10+, macOS, Linux) when Python lacks CA certificates."""
    print("   downloading " + url, flush=True)
    try:
        with urllib.request.urlopen(url, timeout=120) as r:
            return r.read()
    except urllib.error.HTTPError:
        raise
    except OSError as e:          # no connection, or no CA certificates (python.org builds on macOS)
        curl = shutil.which("curl")
        if not curl:
            raise
        print("   urllib failed ({}), retrying with curl".format(e), flush=True)
        r = subprocess.run([curl, "-fsSL", url], stdout=subprocess.PIPE)
        if r.returncode:
            raise OSError("curl could not download {} (exit code {})".format(url, r.returncode))
        return r.stdout


def install_monitor_ui(py):
    """Put mpf-monitor's core/ui/*.ui files into the environment of py when they are missing; returns how many."""
    out = subprocess.run([py, "-c", "import mpfmonitor, os; print(os.path.dirname(mpfmonitor.__file__))"],
                         capture_output=True, text=True, check=True)
    ui_dir = os.path.join(out.stdout.strip(), "core", "ui")
    os.makedirs(ui_dir, exist_ok=True)
    added = 0
    for name in tc.MPF_MONITOR_UI_FILES:
        dst = os.path.join(ui_dir, name)
        if os.path.exists(dst):
            continue
        data = download(tc.MPF_MONITOR_UI_URL + name)
        if b"<ui" not in data[:200]:
            raise SystemExit("{} is not a Qt Designer file".format(tc.MPF_MONITOR_UI_URL + name))
        with open(dst, "wb") as f:
            f.write(data)
        added += 1
    print("   {} added, {} in place ({})".format(added, len(tc.MPF_MONITOR_UI_FILES) - added, ui_dir), flush=True)
    return added


def extract_folder(data, prefix, dest):
    """Unpack the files under prefix ("top/sub/") of a zip into dest; returns how many."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = [n for n in z.namelist() if n.startswith(prefix) and not n.endswith("/")]
        for name in names:
            dst = os.path.join(dest, *name[len(prefix):].split("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as f:
                f.write(z.read(name))
    return len(names)


def unzip(data, dest, os_name):
    if os_name == "macos" and shutil.which("ditto"):
        # ditto keeps the app bundle's permissions, symlinks and code signature
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
            f.write(data)
        try:
            subprocess.run(["ditto", "-x", "-k", f.name, dest], check=True)
        finally:
            os.unlink(f.name)
        return
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            z.extract(info, dest)
            mode = info.external_attr >> 16
            if mode and os_name != "windows":
                os.chmod(os.path.join(dest, info.filename), mode & 0o777)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--dry-run", action="store_true", help="print the plan, change nothing")
    p.add_argument("--os", choices=["windows", "macos", "linux"], help="plan for another OS (implies --dry-run)")
    p.add_argument("--arch", choices=["x86_64", "arm64"], help="plan for another CPU (implies --dry-run)")
    p.add_argument("--monitor", dest="monitor", action="store_true",
                   help="install MPF Monitor {} (the default)".format(tc.MPF_MONITOR_VERSION))
    p.add_argument("--no-monitor", dest="monitor", action="store_false", help="leave MPF Monitor out")
    p.set_defaults(monitor=True)
    p.add_argument("--vpx", action="store_true",
                   help="also install the Visual Pinball X bridge's packages (olefile; pywin32 on Windows)")
    p.add_argument("--upgrade", action="store_true", help="re-run pip install even if MPF is there")
    p.add_argument("--skip-godot", action="store_true", help="no Godot, GMC or Godot import (MPF and tests only)")
    p.add_argument("--skip-media", action="store_true", help="no generated media (config only)")
    args = p.parse_args(argv)
    s = Setup(args)
    s.say("Workspace {} on {} {}{}".format(tc.ROOT, s.os, s.arch, " (dry run)" if s.dry else ""))
    s.assets()
    s.venv()
    if not args.skip_godot:
        s.godot()
        s.gmc()
    if args.skip_media:
        s.say("== MPF config generated from the asset package")
        s.run([tc.venv_python(s.os), os.path.join(tc.ROOT, "scripts", "gen_config.py")], cwd=tc.ROOT)
    else:
        s.generate()
        pup_setup.setup(tc.venv_python(s.os), s.dry)  # PuP Pack: docs/pup.md
    if not args.skip_godot:
        s.godot_import()
        if not args.skip_media and not s.dry:
            tc.write_media_stamp()          # scripts/run.py regenerates when this no longer matches
    s.say("Done. Run `python scripts/run.py` (Godot + MPF), or `python scripts/render_check.py` without a screen.")
    if args.vpx:
        s.say("Visual Pinball X (docs/vpx.md): register the bridge once, as Administrator: "
              "`python scripts/vpx_bridge.py --register`, then `python scripts/vpx_table.py <table.vpx>`.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
