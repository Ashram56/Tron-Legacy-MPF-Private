#!/usr/bin/env python3
"""Start the game on Windows, macOS or Linux: Godot (GMC, the BCP server) first, then MPF, optionally MPF Monitor.

    python scripts/run.py                          # virtual hardware (hw_virtual: smart_virtual, trough full)
    python scripts/run.py --monitor                # ... plus MPF Monitor (setup.py installs it)
    python scripts/run.py --hw proc                # the real machine on the P-ROC (Godot feeds the DMD), a Pro
    python scripts/run.py --hw proc --machine le   # the same on an LE (docs/hardware.md, "Pro or LE")
    python scripts/run.py --hw vpx                 # Visual Pinball X plays the table (docs/vpx.md); MPF waits for it
    python scripts/run.py --scenario NAME          # play scenarios/NAME.txt or assets/rules/traces/NAME.txt in real time
    python scripts/run.py --seconds 20             # stop everything after 20 s
    python scripts/run.py --no-free-play           # factory pricing: coins needed (virtual defaults to free play)
    python scripts/run.py --dmd classic            # the original 128x32 DMD dots (default: hd, smooth text and art)
    python scripts/run.py --dmd-size 1920x480      # DMD window size (hd scales to any size; resize it freely)
    python scripts/run.py --dmd-dots 2             # hd with a dot-matrix look (2 dots per DMD dot, 1 = 128x32)
    python scripts/run.py --dmd-font orbitron      # hd text font: rajdhani (default), orbitron, godot, rom (ROM dots) or a .ttf
    python scripts/run.py --dmd-text-scale 0.85    # hd text size (1 = the ROM's capital height; default 0.85)
    python scripts/run.py --dmd-tint orange        # hd in the original orange (default: Tron blue)
    python scripts/run.py --dmd-text-color "#2a6cff" --dmd-text-glow 0.8   # hd text colour and glow (default 0.8; 0 = none)

Godot's log goes to game/logs/godot.log. MPF runs in this terminal; quitting it (Ctrl+C or Esc in its text UI)
stops Godot and MPF Monitor too. On Linux without a display, Godot runs under Xvfb (xvfb-run).
"""
import argparse
import errno
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gmc_patch  # noqa: E402
from pup import pup_setup  # noqa: E402  (PuP Pack: docs/pup/README.md)
import toolchain as tc  # noqa: E402

IS_WINDOWS = os.name == "nt"


def port_in_use(port):
    """True when something listens on port. Binds instead of connecting: GMC quits when its client hangs up."""
    # Godot listens on "*", an IPv6 socket that also takes IPv4 on Linux but not always on Windows: probe both.
    probes = [(socket.AF_INET, ""), (socket.AF_INET, "127.0.0.1")]
    if socket.has_ipv6:
        probes += [(socket.AF_INET6, "::"), (socket.AF_INET6, "::1")]
    for family, host in probes:
        try:
            s = socket.socket(family, socket.SOCK_STREAM)
        except OSError:         # no IPv6 stack
            continue
        with s:
            if IS_WINDOWS:      # without it a Windows bind can share a port that is taken
                s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:               # ignore TIME_WAIT leftovers of the last run; a listener still blocks the bind
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if family == socket.AF_INET6:
                s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            try:
                s.bind((host, port))
            except OSError as e:
                if family == socket.AF_INET6 and e.errno in (errno.EADDRNOTAVAIL, errno.EAFNOSUPPORT):
                    continue    # IPv6 present but no ::1 / disabled
                return True
    return False


def log_says(path, marker):
    """True when the log file at path contains marker (GMC logs "GMC listening on port 5050")."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return marker in f.read()
    except OSError:
        return False


def log_tail(path, lines=15):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return "".join(f.readlines()[-lines:])
    except OSError:
        return ""


def wait_for_port(port, procs, timeout, log=None, marker=None):
    """Wait until port is taken (or log shows marker); fail early when one of procs exits."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if port_in_use(port) or (marker and log_says(log, marker)):
            return True
        for p in procs:
            if p.poll() is not None:
                return False
        time.sleep(0.2)
    return False


def spawn(cmd, *, log=None, cwd=None, env=None, group=False):
    """Start cmd; log is a path (stdout + stderr) or None to inherit the terminal."""
    out = open(log, "w", encoding="utf-8") if log else None
    kw = {}
    if group:       # its own process group, so stop() also ends its children (xvfb-run -> Godot)
        if IS_WINDOWS:
            kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kw["start_new_session"] = True
    proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=out, stderr=subprocess.STDOUT if out else None,
                            stdin=subprocess.DEVNULL if group else None, **kw)
    proc.log_file = out
    proc.group = group
    return proc


def stop(proc, grace=10):
    """Ask proc to end, then kill it after grace seconds."""
    if proc is None:
        return None
    if proc.poll() is None:
        try:
            if proc.group and not IS_WINDOWS:
                os.killpg(proc.pid, signal.SIGTERM)
            else:
                proc.terminate()
            proc.wait(grace)
        except subprocess.TimeoutExpired:
            if proc.group and not IS_WINDOWS:
                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()
            proc.wait()
        except (ProcessLookupError, PermissionError):
            pass
    if proc.log_file:
        proc.log_file.close()
    return proc.returncode


def godot_command(godot_args, virtual_display=None):
    exe = tc.godot_path()
    if not os.path.exists(exe) and not shutil.which(exe):
        raise SystemExit("Godot not found at {} (run `python scripts/setup.py`, or set GODOT)".format(exe))
    cmd = [exe, "--path", tc.GAME] + list(godot_args)
    if ("opengl3" in godot_args or os.environ.get("TRON_RENDER_THREAD") == "0") \
            and "--render-thread" not in godot_args:
        # Godot's separate render thread (game/project.godot) off: --no-render-thread or TRON_RENDER_THREAD=0, and
        # always for the captures' renderer (opengl3), which wrote no frames with it
        cmd[3:3] = ["--render-thread", "safe"]
    if virtual_display is None:
        virtual_display = tc.needs_virtual_display()
    if virtual_display:
        if not shutil.which("xvfb-run"):
            raise SystemExit("no display and no xvfb-run: install xvfb (apt install xvfb) or set DISPLAY")
        cmd = ["xvfb-run", "-a", "-s", "-screen 0 1280x720x24"] + cmd
    return cmd


def core_pinning(godot, mpf, stop_event, interval=2.0):
    """Linux, 4+ usable cores: Godot's main thread gets the last core to itself; Godot's other threads (renderer,
    video decoding, audio) and MPF share the others. Godot's main thread runs the game's scripts and draws every
    frame, so it is the one that must not wait for a core (docs/performance.md: on a Jetson Xavier NX in mode 5,
    +1.5 FPS and a third fewer frames over 2 vblanks). Applied again every `interval` s, as new threads start with
    their creator's cores. TRON_PIN=0 turns it off."""
    cpus = sorted(os.sched_getaffinity(0))
    main_core, others = {cpus[-1]}, set(cpus[:-1])
    while not stop_event.wait(interval):
        for proc, is_godot in ((godot, True), (mpf, False)):
            if proc is None or proc.poll() is not None:
                continue
            try:
                tids = [int(t) for t in os.listdir("/proc/%d/task" % proc.pid)]
            except OSError:
                continue
            for tid in tids:
                want = main_core if is_godot and tid == proc.pid else others
                try:
                    if os.sched_getaffinity(tid) != want:
                        os.sched_setaffinity(tid, want)
                except OSError:
                    pass                # the thread ended meanwhile


def start_core_pinning(godot, mpf, virtual_display):
    """core_pinning() on a thread when it applies (Linux, a real display, 4+ cores); returns its stop event."""
    if not sys.platform.startswith("linux") or virtual_display or os.environ.get("TRON_PIN") == "0" \
            or len(os.sched_getaffinity(0)) < 4:
        return None
    import threading
    stop_event = threading.Event()
    threading.Thread(target=core_pinning, args=(godot, mpf, stop_event), daemon=True).start()
    return stop_event


def keep_screen_on():
    """Linux on a real X display: the X server's own screen saver and DPMS power-off off for this X session (GNOME's
    idle blanking and lock are turned off by install_jetson_hwdec.sh); a cabinet's players use no keyboard or mouse."""
    if IS_WINDOWS or sys.platform == "darwin" or not os.environ.get("DISPLAY") or tc.needs_virtual_display():
        return
    if shutil.which("xset"):
        subprocess.run(["xset", "s", "off", "-dpms"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def user_arg(gargs, arg):
    """gargs plus arg after Godot's "--" (the args game scripts read with OS.get_cmdline_user_args)."""
    return list(gargs) + [arg] if "--" in gargs else list(gargs) + ["--", arg]


def engine_arg(gargs, *args):
    """gargs with Godot engine args (before "--")."""
    gargs = list(gargs)
    at = gargs.index("--") if "--" in gargs else len(gargs)
    return gargs[:at] + list(args) + gargs[at:]


def dmd_args(gargs, dmd=None, dots=None, size=None, text_color=None, text_glow=None, tint=None, font=None,
             text_scale=None):
    """Godot args for the DMD mode (game/tools/dmd_mode.gd): --dmd=hd|classic, --dmd-dots=N, the window
    size (Godot's --resolution WxH), the HD colours (--dmd-tint=blue|orange, --dmd-text-color=#RRGGBB,
    --dmd-text-glow=X), the HD text font (--dmd-font=rajdhani|orbitron|godot|rom|FILE) and its size
    (--dmd-text-scale=X). None leaves the choice to TRON_DMD... / the project settings (hd, blue, glow 0.8,
    rajdhani, 0.85)."""
    if dmd:
        gargs = user_arg(gargs, "--dmd=" + dmd)
    if font:
        gargs = user_arg(gargs, "--dmd-font=" + (os.path.abspath(font) if os.path.isfile(font) else font))
    if tint:
        gargs = user_arg(gargs, "--dmd-tint=" + tint)
    if dots is not None:
        gargs = user_arg(gargs, "--dmd-dots={}".format(dots))
    if size:
        w, _, h = size.lower().partition("x")
        if not (w.isdigit() and h.isdigit()):
            raise SystemExit("--dmd-size: expected WIDTHxHEIGHT, for example 1920x480, not " + size)
        gargs = engine_arg(gargs, "--resolution", "{}x{}".format(int(w), int(h)))
    if text_color:
        if not re.fullmatch(r"#?[0-9a-fA-F]{6}", text_color):
            raise SystemExit("--dmd-text-color: expected a colour like #2a6cff, not " + text_color)
        gargs = user_arg(gargs, "--dmd-text-color=#" + text_color.lstrip("#"))
    if text_glow is not None:
        gargs = user_arg(gargs, "--dmd-text-glow={:g}".format(text_glow))
    if text_scale is not None:
        if not 0.5 <= text_scale <= 1.5:
            raise SystemExit("--dmd-text-scale: expected 0.5 to 1.5, not {:g}".format(text_scale))
        gargs = user_arg(gargs, "--dmd-text-scale={:g}".format(text_scale))
    return gargs


DEFAULT_MACHINE = {"virtual": "pro", "proc": "pro", "vpx": "le"}     # hw_vpx.yaml is the LE: the VPW table is one


def overlay(hw, machine=None, scenario=None):
    """The hardware overlay for a machine: hw_proc / hw_virtual are the Pro, hw_vpx the LE; the other machine adds
    _le / _pro. Scenarios replay the LE ROM's traces, so they default to the LE."""
    default = DEFAULT_MACHINE[hw]
    machine = machine or ("le" if scenario else default)
    return "hw_" + hw + ("" if machine == default else "_" + machine)


def mpf_args(hw, scenario=None, text_ui=False, free_play=None, machine=None, fiber_optics=False):
    """free_play: add config/free_play.yaml (START without a coin); default on for the virtual machine and VPX,
    off for scenarios (the ROM traces insert a coin) and the real machine. machine: "pro" or "le" (overlay());
    fiber_optics: add config/fiber_optics.yaml (drive the ramp light tubes on a Pro)."""
    if free_play is None:
        free_play = hw in ("virtual", "vpx") and not scenario
    configs = ["config", overlay(hw, machine, scenario)] + (["fiber_optics"] if fiber_optics else []) + (
        ["free_play"] if free_play else [])
    args = ["game", ".", "-c", ",".join(configs)]
    if not text_ui:
        args.append("-t")
    if scenario:
        args.append("-X")       # smart_virtual: the scenario's coil pulses move balls (hw_virtual uses it too)
    return args


def ensure_monitor():
    """MPF Monitor in the venv: a workspace set up before setup.py installed it by default (or with
    --no-monitor) gets it now, instead of `mpf monitor` failing."""
    py = tc.venv_python()
    if subprocess.run([py, "-c", "import mpfmonitor"], capture_output=True).returncode == 0:
        return
    print("MPF Monitor is not installed: installing it (scripts/setup.py)", flush=True)
    import argparse
    import setup
    setup.Setup(argparse.Namespace(os=None, arch=None, dry_run=False, monitor=True, upgrade=False)).venv()


def monitor_settings():
    """MPF Monitor keeps its window layout in game/monitor/settings.ini and rewrites it on every run, so git
    tracks settings.ini.default and the first run copies it into place (later runs keep yours)."""
    dst = os.path.join(tc.GAME, "monitor", "settings.ini")
    if not os.path.exists(dst):
        shutil.copyfile(dst + ".default", dst)


def scenario_path(name):
    """--scenario NAME: scenarios/NAME.txt (this repo's own) or assets/rules/traces/NAME.txt; a *.txt path is made
    absolute, since MPF runs in game/."""
    if name.endswith(".txt"):
        return os.path.abspath(name)
    own = os.path.join(tc.ROOT, "scenarios", name + ".txt")
    return own if os.path.exists(own) else name


def run(hw="virtual", *, monitor=False, scenario=None, seconds=None, text_ui=False, free_play=None, godot_args=(),
        godot_log=None, mpf_log=None, trace=None, virtual_display=None, wait_godot_exit=False, machine=None,
        fiber_optics=False):
    """Godot, then MPF (and MPF Monitor); returns MPF's exit code. Everything is stopped on the way out."""
    logs = os.path.join(tc.GAME, "logs")
    os.makedirs(logs, exist_ok=True)
    godot_log = godot_log or os.path.join(logs, "godot.log")
    gargs = list(godot_args)
    if hw == "proc" and "--proc-dmd" not in gargs:    # also keeps the DMD classic: the P-ROC takes 128x32
        gargs = user_arg(gargs, "--proc-dmd")
    gmc_patch.patch()                   # GMC 1.0.0 drops BCP messages split across reads (sounds, music)
    stale = tc.media_stale()
    if stale:                           # e.g. after a pull: the display would show the old effects
        print("Generated media out of date ({}): generating and importing them again".format(stale), flush=True)
        import setup
        setup.refresh_media()
    if port_in_use(tc.BCP_PORT):
        raise SystemExit("port {} is already taken: is another Godot/GMC running?".format(tc.BCP_PORT))
    env = dict(os.environ)
    if scenario:
        env["TRON_LIVE_SCENARIO"] = scenario_path(scenario)
    if trace:
        env["TRON_TRACE"] = trace
    godot = mpf = mon = pinning = None
    print(pup_setup.status()[1], flush=True)  # PuP Pack: docs/pup/README.md
    if not virtual_display:
        keep_screen_on()
    try:
        godot = spawn(godot_command(gargs, virtual_display), log=godot_log, group=True)
        print("Godot started (log: {}), waiting for GMC on port {}".format(godot_log, tc.BCP_PORT), flush=True)
        if not wait_for_port(tc.BCP_PORT, [godot], 120, godot_log, "GMC listening on port"):
            godot.log_file.flush()
            raise SystemExit("GMC did not open port {}{}; last lines of {}:\n{}".format(
                tc.BCP_PORT, " (Godot exited)" if godot.poll() is not None else "", godot_log,
                log_tail(godot_log)))
        print("GMC is listening", flush=True)
        margs = mpf_args(hw, scenario, text_ui, free_play, machine, fiber_optics)
        print("Starting MPF: mpf " + " ".join(margs), flush=True)
        mpf = spawn(tc.mpf_command() + margs, log=mpf_log, cwd=tc.GAME, env=env)
        pinning = start_core_pinning(godot, mpf, virtual_display if virtual_display is not None
                                     else tc.needs_virtual_display())
        if hw == "vpx":
            print("MPF waits for the Visual Pinball X table (TronMPF.Controller) on port {}: start the table "
                  "now (docs/vpx.md)".format(tc.MONITOR_PORT), flush=True)
        if monitor:
            ensure_monitor()
            monitor_settings()
            print("waiting for MPF's BCP server on port {} for MPF Monitor".format(tc.MONITOR_PORT), flush=True)
            if wait_for_port(tc.MONITOR_PORT, [mpf], 120):
                mon = spawn(tc.mpf_command() + ["monitor"], cwd=tc.GAME, group=True,
                            log=os.path.join(logs, "monitor.log"))
                print("MPF Monitor started (log: game/logs/monitor.log)", flush=True)
            else:
                print("MPF did not open port {}: no MPF Monitor".format(tc.MONITOR_PORT), flush=True)
        try:
            mpf.wait(seconds)
        except subprocess.TimeoutExpired:
            print("{} s elapsed, stopping MPF".format(seconds), flush=True)
            stop(mpf)
            mpf.returncode = 0          # a planned stop, not a failure
        if wait_godot_exit:         # a Godot capture run quits on its own when its time is up
            try:
                godot.wait(30)
            except subprocess.TimeoutExpired:
                pass
        return mpf.returncode
    except KeyboardInterrupt:
        print("interrupted, stopping", flush=True)
        return 130
    finally:
        if pinning:
            pinning.set()
        for p in (mon, mpf, godot):
            stop(p)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--hw", choices=["virtual", "proc", "vpx"], default="virtual",
                   help="hardware overlay: game/config/hw_<hw>.yaml (default virtual)")
    p.add_argument("--machine", choices=["pro", "le"],
                   help="Tron Legacy Pro or LE IO assignments (default pro; le with --hw vpx, the VPW table, and with "
                        "--scenario, the LE ROM's traces)")
    p.add_argument("--fiber-optics", action="store_true",
                   help="drive the ramp light tubes on a Pro too (always on with an LE)")
    p.add_argument("--monitor", action="store_true", help="also start MPF Monitor (layout in game/monitor/)")
    p.add_argument("--scenario", help="play scenarios/NAME.txt or assets/rules/traces/NAME.txt (or a script file *.txt) in real time "
                                      "(smart_virtual)")
    p.add_argument("--seconds", type=float, help="stop after this many seconds")
    p.add_argument("--trace", help="write MPF's trace (jsonl) to this file")
    p.add_argument("--text-ui", dest="text_ui", action="store_true", default=None,
                   help="MPF's text UI (default: on in a terminal without --seconds)")
    p.add_argument("--no-text-ui", dest="text_ui", action="store_false")
    p.add_argument("--free-play", dest="free_play", action="store_true", default=None,
                   help="START without a coin (default with --hw virtual or vpx and no --scenario)")
    p.add_argument("--no-free-play", dest="free_play", action="store_false",
                   help="the factory pricing: insert coins (key 5 in the DMD window, or s_coin in MPF Monitor)")
    p.add_argument("--dmd", choices=["hd", "classic"],
                   help="DMD look: hd (default; text and art drawn at the window's resolution) or classic (the "
                        "original 128x32 dots, exactly as the ROM draws them). Also TRON_DMD=classic. --hw proc "
                        "is always classic")
    p.add_argument("--dmd-dots", type=int, metavar="N",
                   help="hd only: dot-matrix look with N dots per DMD dot (1 = the 128x32 grid; 0 = off, default)")
    p.add_argument("--dmd-size", metavar="WxH", help="DMD window size, for example 1920x480 (default 1024x256)")
    p.add_argument("--dmd-tint", choices=["blue", "orange"],
                   help="hd only: DMD colour, text and effects: blue (default, Tron blue #2a6cff) or orange (the "
                        "original DMD's). Also TRON_DMD_TINT")
    p.add_argument("--dmd-text-color", metavar="#RRGGBB",
                   help="hd only: text colour (default the tint's: #2a6cff). Also TRON_DMD_TEXT_COLOR")
    p.add_argument("--dmd-text-glow", type=float, metavar="X",
                   help="hd only: strength of the glow around the text (default 0.8, soft; 0 = none). Also "
                        "TRON_DMD_TEXT_GLOW")
    p.add_argument("--dmd-font", metavar="NAME",
                   help="hd only: font of the DMD text: rajdhani (default, clean), orbitron (Tron style, wider), "
                        "godot (Godot's default font), rom (the ROM's own dot fonts, smoothed) or a .ttf/.otf "
                        "file. Clean fonts keep the ROM's placement. Also TRON_DMD_FONT")
    p.add_argument("--dmd-text-scale", type=float, metavar="X",
                   help="hd only, clean fonts: text size, 1 = capitals as tall as the ROM's (default 0.85; 0.5-1.5). "
                        "Also TRON_DMD_TEXT_SCALE")
    p.add_argument("--no-render-thread", dest="render_thread", action="store_false",
                   help="draw on Godot's main thread instead of its separate render thread (the default, "
                        "docs/performance.md), should a GPU driver misbehave with it. Also TRON_RENDER_THREAD=0")
    p.add_argument("godot_args", nargs="*", help="extra Godot arguments, after --")
    args = p.parse_args(argv)
    if not args.render_thread and "--render-thread" not in args.godot_args:
        args.godot_args = engine_arg(args.godot_args, "--render-thread", "safe")
    text_ui = args.text_ui
    if text_ui is None:
        text_ui = sys.stdin.isatty() and sys.stdout.isatty() and args.seconds is None
    return run(args.hw, machine=args.machine, fiber_optics=args.fiber_optics, monitor=args.monitor,
               scenario=args.scenario, seconds=args.seconds, text_ui=text_ui,
               free_play=args.free_play, godot_args=dmd_args(args.godot_args, args.dmd, args.dmd_dots, args.dmd_size,
                                                     args.dmd_text_color, args.dmd_text_glow, args.dmd_tint,
                                                     args.dmd_font, args.dmd_text_scale),
               trace=args.trace and os.path.abspath(args.trace))


if __name__ == "__main__":
    sys.exit(main() or 0)
