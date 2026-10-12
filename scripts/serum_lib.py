#!/usr/bin/env python3
"""libserum itself (https://github.com/PPUC/libserum, the colouriser of PinMAME, VPX, DMDExt and ZeDMD), loaded with
ctypes: the reference scripts/serum.py is checked against (tests/test_serum.py), and what the colour build uses for
the 2x frames when it is there (libserum's own Scale2x, the one the colourisation's author saw).

libserum is a C++ library: it is not installed by setup.py (it needs CMake and a compiler). Build it once with

    .venv/bin/python scripts/serum_lib.py build          # clones libserum + libframeutil into .cache/libserum, CMake
    .venv/bin/python scripts/serum_lib.py info           # the version and the loaded colourisation

or point TRON_LIBSERUM at a libserum shared library (libserum.so / libserum.dylib / serum64.dll). Without it, the
colour build uses scripts/serum.py alone (the same colours; its own Scale2x port).
"""
import ctypes
import glob
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CACHE = os.path.join(ROOT, ".cache", "libserum")
CROM = os.path.join(ROOT, "serum", "trn_174h.cRZ")
# pinned: the libserum release line this was checked with, and the libframeutil revision its config.sh pins
LIBSERUM_REF = "v2.8.0"
LIBSERUM_URL = "https://github.com/PPUC/libserum.git"
LIBFRAMEUTIL_URL = "https://github.com/PPUC/libframeutil.git"

FLAG_REQUEST_32P_FRAMES = 1
FLAG_REQUEST_64P_FRAMES = 2
IDENTIFY_NO_FRAME = 0xFFFFFFFF


class FrameStruc(ctypes.Structure):
    _fields_ = [("frame", ctypes.POINTER(ctypes.c_uint8)), ("palette", ctypes.POINTER(ctypes.c_uint8)),
                ("rotations", ctypes.POINTER(ctypes.c_uint8)),
                ("frame32", ctypes.POINTER(ctypes.c_uint16)), ("width32", ctypes.c_uint32),
                ("rotations32", ctypes.POINTER(ctypes.c_uint16)), ("rotationsinframe32", ctypes.POINTER(ctypes.c_uint16)),
                ("modifiedelements32", ctypes.POINTER(ctypes.c_uint8)),
                ("frame64", ctypes.POINTER(ctypes.c_uint16)), ("width64", ctypes.c_uint32),
                ("rotations64", ctypes.POINTER(ctypes.c_uint16)), ("rotationsinframe64", ctypes.POINTER(ctypes.c_uint16)),
                ("modifiedelements64", ctypes.POINTER(ctypes.c_uint8)),
                ("SerumVersion", ctypes.c_uint32), ("flags", ctypes.c_uint8), ("nocolors", ctypes.c_uint32),
                ("ntriggers", ctypes.c_uint32), ("triggerID", ctypes.c_uint32), ("frameID", ctypes.c_uint32),
                ("rotationtimer", ctypes.c_uint32)]


def library_path():
    """The libserum shared library: TRON_LIBSERUM, else the one `build` made; None when there is none."""
    env = os.environ.get("TRON_LIBSERUM")
    if env:
        return env if os.path.exists(env) else None
    names = ("libserum.so", "libserum.dylib", "serum64.dll", "serum.dll", "libserum64.so", "libserum64.dylib")
    for n in names:
        for p in glob.glob(os.path.join(CACHE, "**", n), recursive=True):
            return p
    return None


class LibSerum:
    """One loaded colourisation in libserum (process-wide state: one at a time)."""

    def __init__(self, crom=CROM, lib=None):
        path = lib or library_path()
        if not path:
            raise OSError("libserum not found: scripts/serum_lib.py build, or set TRON_LIBSERUM")
        self.lib = ctypes.CDLL(path)
        L = self.lib
        L.Serum_Load.restype = ctypes.POINTER(FrameStruc)
        L.Serum_Load.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint8]
        L.Serum_Colorize.restype = ctypes.c_uint32
        L.Serum_Colorize.argtypes = [ctypes.POINTER(ctypes.c_uint8)]
        L.Serum_Rotate.restype = ctypes.c_uint32
        L.Serum_GetVersion.restype = ctypes.c_char_p
        L.Serum_SetGenerateCRomC.argtypes = [ctypes.c_bool]
        L.Serum_SetIgnoreUnknownFramesTimeout.argtypes = [ctypes.c_uint16]
        L.Serum_SetMaximumUnknownFramesToSkip.argtypes = [ctypes.c_uint8]
        # libserum reads altcolor/<rom>/<rom>.cRZ (or .cROM): a private copy, so no .cROMc lands next to ours
        self._dir = tempfile.mkdtemp(prefix="libserum_")
        rom = os.path.splitext(os.path.basename(crom))[0]
        os.makedirs(os.path.join(self._dir, rom))
        shutil.copyfile(crom, os.path.join(self._dir, rom, os.path.basename(crom)))
        L.Serum_SetGenerateCRomC(False)
        p = L.Serum_Load(self._dir.encode() + b"/", rom.encode(), FLAG_REQUEST_32P_FRAMES)
        if not p:
            raise OSError("libserum could not load %s" % crom)
        self.s = p.contents
        L.Serum_SetIgnoreUnknownFramesTimeout(0)
        L.Serum_SetMaximumUnknownFramesToSkip(0)
        self.version = L.Serum_GetVersion().decode()

    def colorize(self, frame):
        """(colour indices 128x32, palette [(r, g, b)] * 64, frame id or None) of a frame of shades 0..15 (bytes),
        as libserum leaves its output after Serum_Colorize (an unknown frame keeps the last colours)."""
        buf = (ctypes.c_uint8 * len(frame)).from_buffer_copy(frame)
        ret = self.lib.Serum_Colorize(buf)
        fid = None if ret == IDENTIFY_NO_FRAME else self.s.frameID
        idx = bytes(ctypes.string_at(self.s.frame, len(frame)))
        pal = ctypes.string_at(self.s.palette, 64 * 3)
        return idx, [tuple(pal[3 * k:3 * k + 3]) for k in range(64)], fid

    def close(self):
        self.lib.Serum_Dispose()
        shutil.rmtree(self._dir, True)


def build():
    """Clone and build libserum (shared library) into .cache/libserum with CMake; returns the library's path."""
    for tool in ("git", "cmake"):
        if not shutil.which(tool):
            raise SystemExit("serum_lib build: %s is needed" % tool)
    src, fu = os.path.join(CACHE, "libserum"), os.path.join(CACHE, "libframeutil")
    if not os.path.isdir(src):
        subprocess.check_call(["git", "clone", "--depth", "1", "--branch", LIBSERUM_REF, LIBSERUM_URL, src])
    sha = None
    with open(os.path.join(src, "platforms", "config.sh"), encoding="utf-8") as f:
        for line in f:
            if line.startswith("LIBFRAMEUTIL_SHA="):
                sha = line.split("=", 1)[1].strip()
    if not os.path.isdir(fu):
        subprocess.check_call(["git", "clone", "-q", LIBFRAMEUTIL_URL, fu])
    if sha:
        subprocess.check_call(["git", "-C", fu, "checkout", "-q", sha])
    shutil.copyfile(os.path.join(fu, "include", "FrameUtil.h"), os.path.join(src, "third-party", "include", "FrameUtil.h"))
    plat = {"win32": "win", "darwin": "macos"}.get(sys.platform, "linux")
    arch = "aarch64" if os.uname().machine in ("aarch64", "arm64") and plat == "linux" else (
        "arm64" if os.uname().machine == "arm64" else "x64") if hasattr(os, "uname") else "x64"
    out = os.path.join(src, "build")
    subprocess.check_call(["cmake", "-S", src, "-B", out, "-DCMAKE_BUILD_TYPE=Release", "-DBUILD_STATIC=OFF",
                           "-DPLATFORM=" + plat, "-DARCH=" + arch])
    subprocess.check_call(["cmake", "--build", out, "--config", "Release", "-j", str(os.cpu_count() or 2)])
    return library_path()


def main(argv):
    if argv[:1] == ["build"]:
        print(build())
        return 0
    if argv[:1] == ["info"]:
        ls = LibSerum(argv[1] if len(argv) > 1 else CROM)
        print("libserum %s (%s): Serum v%d, %d shades" % (ls.version, library_path(), ls.s.SerumVersion, ls.s.nocolors))
        ls.close()
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
