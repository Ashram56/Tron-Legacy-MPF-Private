"""The pinned toolchain and every per-OS path of this workspace, in one place.

Standard library only: scripts/setup.py imports it before any venv exists. Every script that runs MPF,
Godot or the venv's Python takes the path from here, so Windows, macOS and Linux differ in this file only.

    .venv/                 Python venv: Scripts\\python.exe on Windows, bin/python elsewhere
    tools/godot/           Godot, unpacked from the official release zip for the host:
                             Windows  Godot_v<ver>-stable_win64.exe        (windows_arm64.exe on ARM)
                             macOS    Godot.app/Contents/MacOS/Godot       (universal: Intel and Apple silicon)
                             Linux    Godot_v<ver>-stable_linux.x86_64     (linux.arm64 on ARM)
    game/addons/mpf-gmc/   the GMC add-on (Godot media controller)

The environment variable GODOT overrides the Godot executable (a Godot you installed yourself), TRON_VENV the
venv (the Docker image keeps its venv in /opt/venv, outside the bind-mounted repository: docker/README.md).
"""
import os
import platform
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
GAME = os.path.join(ROOT, "game")

PYTHON_MIN = (3, 10)
MPF_VERSION = "0.80.1"
GODOT_VERSION = "4.6.3"
GMC_VERSION = "1.0.0"
MPF_MONITOR_VERSION = "1.0.0"
# ruamel.yaml.clib: 0.2.15 wheels name their metadata ruamel_yaml_clib, which MPF's pkg_resources (setuptools 72)
# cannot match to ruamel.yaml's requirement; with MPF Monitor installed `mpf` then fails to start. 0.2.14 is the
# last with the dotted name. Python 3.13+ does not use the C library.
# fonttools: the HD mode's vector fonts (scripts/font_outline.py)
REQUIREMENTS = ["mpf==" + MPF_VERSION, "pillow>=10.1", "fonttools>=4.40", "pytest",
                'ruamel.yaml.clib==0.2.14; python_version < "3.13"']
# PyQt6 6.8+ ships Linux arm64 wheels for glibc 2.39+ only (Ubuntu 24.04); 6.7 has them for glibc 2.28+, which
# JetPack 5 (2.31) and 6 (2.35) need: without a wheel pip tries the sdist, which needs qmake
MONITOR_REQUIREMENTS = ["mpf-monitor==" + MPF_MONITOR_VERSION,
                        'PyQt6>=6.4.2,<6.8; sys_platform == "linux" and platform_machine == "aarch64"']
# Visual Pinball X (setup.py --vpx): olefile reads the table's script out of the .vpx (scripts/vpx_table.py),
# pywin32 runs the TronMPF.Controller COM server VPX talks to (scripts/vpx_bridge.py, Windows only).
VPX_REQUIREMENTS = ["olefile>=0.46", 'pywin32>=306; sys_platform == "win32"']
# mpf-monitor 1.0.0 on PyPI (wheel and sdist) lacks its Qt Designer files, so `mpf monitor` stops with
# "searchable_tree.ui: No such file". setup.py puts them in from the release's git tag.
MPF_MONITOR_UI_FILES = ("events_table.ui", "inspector.ui", "searchable_table.ui", "searchable_tree.ui")
MPF_MONITOR_UI_URL = ("https://raw.githubusercontent.com/missionpinball/mpf-monitor/v{}/mpfmonitor/core/ui/"
                      .format(MPF_MONITOR_VERSION))

BCP_PORT = 5050             # GMC (Godot) is the BCP server, MPF connects to it
MONITOR_PORT = 5051         # MPF's own BCP server, MPF Monitor connects to it

GODOT_RELEASES = "https://github.com/godotengine/godot/releases/download/{0}-stable/".format(GODOT_VERSION)
GMC_ZIP = "https://github.com/missionpinball/mpf-gmc/archive/refs/tags/v{0}.zip".format(GMC_VERSION)
GMC_GIT = "https://github.com/missionpinball/mpf-gmc"
GMC_DIR = os.path.join(GAME, "addons", "mpf-gmc")


def host_os(system=None):
    """'windows', 'macos' or 'linux' (system defaults to platform.system())."""
    system = (system or platform.system()).lower()
    if system.startswith(("windows", "cygwin", "msys")) or system == "nt":
        return "windows"
    if system in ("darwin", "macos", "mac"):
        return "macos"
    if system == "linux":
        return "linux"
    raise SystemExit("unsupported OS {!r}: Windows, macOS or Linux only".format(system))


def host_arch(machine=None):
    """'x86_64' or 'arm64' (machine defaults to platform.machine())."""
    machine = (machine or platform.machine()).lower()
    if machine in ("x86_64", "amd64", "x64", "x86-64"):
        return "x86_64"
    if machine in ("arm64", "aarch64", "armv8", "armv8l"):
        return "arm64"
    raise SystemExit("unsupported CPU {!r}: x86_64 or arm64 only".format(machine))


# ---------------------------------------------------------------------- Python venv

def venv_dir(root=ROOT):
    """root/.venv, or $TRON_VENV for this workspace when it is set."""
    if os.environ.get("TRON_VENV") and root == ROOT:
        return os.environ["TRON_VENV"]
    return os.path.join(root, ".venv")


def venv_bin(os_name=None, root=ROOT):
    return os.path.join(venv_dir(root), "Scripts" if host_os(os_name) == "windows" else "bin")


def venv_exe(name, os_name=None, root=ROOT):
    """A console script or the interpreter of the venv: venv_exe('python'), venv_exe('mpf')."""
    exe = name + ".exe" if host_os(os_name) == "windows" else name
    return os.path.join(venv_bin(os_name, root), exe)


def venv_python(os_name=None, root=ROOT):
    return venv_exe("python", os_name, root)


def python():
    """The venv's Python when it exists, else the one running this script (CI may use its own)."""
    exe = venv_python()
    return exe if os.path.exists(exe) else sys.executable


def mpf_command():
    """How to start MPF: the venv's mpf script, else `python -m mpf` from the running interpreter."""
    exe = venv_exe("mpf")
    return [exe] if os.path.exists(exe) else [python(), "-m", "mpf"]


# ---------------------------------------------------------------------- Godot

def godot_asset(os_name=None, arch=None):
    """The release zip of the official Godot build for this OS and CPU."""
    os_name, arch = host_os(os_name), host_arch(arch)
    suffix = {("windows", "x86_64"): "win64.exe", ("windows", "arm64"): "windows_arm64.exe",
              ("macos", "x86_64"): "macos.universal", ("macos", "arm64"): "macos.universal",
              ("linux", "x86_64"): "linux.x86_64", ("linux", "arm64"): "linux.arm64"}[(os_name, arch)]
    return "Godot_v{}-stable_{}.zip".format(GODOT_VERSION, suffix)


def godot_url(os_name=None, arch=None):
    return GODOT_RELEASES + godot_asset(os_name, arch)


def godot_dir(root=ROOT):
    return os.path.join(root, "tools", "godot")


def godot_relpath(os_name=None, arch=None):
    """The executable inside tools/godot/, as the release zip unpacks it."""
    os_name = host_os(os_name)
    if os_name == "macos":
        return os.path.join("Godot.app", "Contents", "MacOS", "Godot")
    return godot_asset(os_name, arch)[:-len(".zip")]       # the zip holds one file named like itself


def godot_path(os_name=None, arch=None, root=ROOT):
    """The Godot executable: $GODOT if set, else the pinned build in tools/godot/."""
    if os.environ.get("GODOT") and os_name is None:
        return os.environ["GODOT"]
    return os.path.join(godot_dir(root), godot_relpath(os_name, arch))


def godot_command(*args):
    return [godot_path(), "--path", GAME] + list(args)


# ---------------------------------------------------------------------- generated media

# What the generated config and media (game/config/rom, game/media, game/slides/deffs, game/fonts,
# game/tron/media_data.json; all git-ignored) are made from: a change to any of these after a pull leaves
# the workspace showing the old display effects until they are generated and imported again.
MEDIA_INPUTS = [os.path.join("scripts", n) for n in ("gen_config.py", "gen_media.py", "gen_fonts.py", "rom_layout.py",
                                                       "dmd_hd.py", "font_outline.py", "dmd_color.py", "serum.py")] \
    + [os.path.join("game", "tools", "dmd_colormap.json"), os.path.join("serum", "trn_174h.cRZ")] \
    + [os.path.join("assets", "mpf_package", n) for n in ("event_map.csv", "lamp_effects.csv")] \
    + [os.path.join("assets", "code", "tron_game_decompiled_v2.c")]
MEDIA_STAMP = os.path.join(GAME, "media", ".generated")


def media_fingerprint(root=ROOT):
    import hashlib
    h = hashlib.sha1()
    for rel in MEDIA_INPUTS:
        path = os.path.join(root, rel)
        h.update(rel.replace(os.sep, "/").encode())
        if os.path.exists(path):
            with open(path, "rb") as f:
                h.update(hashlib.sha1(f.read()).digest())
    return h.hexdigest()


def media_stale(root=ROOT):
    """Why the generated media must be made again (None when current): never generated or stamped, made
    from other generator scripts or assets than these, or generated but not imported by Godot (the
    slides then show no picture: Godot loads a PNG only through its .import file)."""
    stamp = os.path.join(root, "game", "media", ".generated")
    if not os.path.exists(stamp):
        return "no stamp of a complete media generation and Godot import ({})".format(stamp)
    with open(stamp, encoding="utf-8") as f:
        if f.read().strip() != media_fingerprint(root):
            return "the generator scripts or the asset package changed since the media were generated"
    for folder in ("dmd", "dmd_hd"):
        probe = os.path.join(root, "game", "media", folder, "deff_091", "solid0.png")
        if os.path.exists(probe) and not os.path.exists(probe + ".import"):
            return "the media were generated but not imported by Godot"
    return None


def write_media_stamp(root=ROOT):
    with open(os.path.join(root, "game", "media", ".generated"), "w", encoding="utf-8") as f:
        f.write(media_fingerprint(root) + "\n")


# ---------------------------------------------------------------------- display

def needs_virtual_display(os_name=None, environ=None):
    """True on Linux without a display server: run Godot under Xvfb (xvfb-run)."""
    environ = os.environ if environ is None else environ
    return host_os(os_name) == "linux" and not (environ.get("DISPLAY") or environ.get("WAYLAND_DISPLAY"))


if __name__ == "__main__":
    print("host        ", host_os(), host_arch())
    print("venv python ", venv_python(), "(present)" if os.path.exists(venv_python()) else "(missing)")
    print("godot       ", godot_path(), "(present)" if os.path.exists(godot_path()) else "(missing)")
    print("godot zip   ", godot_url())
    print("gmc         ", GMC_DIR, "(present)" if os.path.exists(os.path.join(GMC_DIR, "plugin.cfg")) else "(missing)")
