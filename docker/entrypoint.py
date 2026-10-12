#!/usr/bin/env python3
"""Entry point of the Docker image (docker/README.md): one role per compose service.

    setup         generate the MPF config and media, fetch GMC, import the Godot project (skipped when done)
    godot         GMC, the DMD window and the BCP server on port 5050
    mpf           MPF, once GMC listens; hw_virtual, or hw_proc with TRON_HW=proc
    monitor       MPF Monitor, once MPF's own BCP server listens on port 5051
    render-check  scripts/render_check.py under Xvfb (no screen needed)
    test          pytest -q tests
    shell         bash (or any other command given after the role)

The repository is bind-mounted at /workspace; the venv (TRON_VENV) and Godot (GODOT) live in the image. Window
placement comes from the environment: DMD_SCREEN, DMD_POSITION, DMD_RESOLUTION, DMD_FULLSCREEN, GODOT_ARGS,
GODOT_RENDERING_DRIVER, and DMD_DISPLAY / MONITOR_DISPLAY to put a window on another X display.
"""
import os
import shlex
import subprocess
import sys
import time

WORKSPACE = os.environ.get("TRON_WORKSPACE", "/workspace")
sys.path.insert(0, os.path.join(WORKSPACE, "scripts"))


def say(text):
    print("[tron] " + text, flush=True)


def truthy(value):
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def hardware(env):
    hw = (env.get("TRON_HW") or "virtual").strip().lower()
    if hw not in ("virtual", "proc"):
        raise SystemExit("TRON_HW must be virtual or proc, not {!r}".format(hw))
    return hw


def machine(env):
    value = (env.get("TRON_MACHINE") or "").strip().lower()
    if value not in ("", "pro", "le"):
        raise SystemExit("TRON_MACHINE must be pro or le, not {!r}".format(value))
    return value or None


def godot_args(env):
    """Godot's command line options for the DMD window, from the environment."""
    args = []
    driver = env.get("GODOT_RENDERING_DRIVER", "").strip()
    if driver:
        args += ["--rendering-driver", driver]
    if env.get("DMD_SCREEN", "").strip():
        args += ["--screen", env["DMD_SCREEN"].strip()]
    if env.get("DMD_POSITION", "").strip():
        args += ["--position", env["DMD_POSITION"].strip()]
    if env.get("DMD_RESOLUTION", "").strip():
        args += ["--resolution", env["DMD_RESOLUTION"].strip()]
    if truthy(env.get("DMD_FULLSCREEN")):
        args.append("--fullscreen")
    if env.get("TRON_RENDER_THREAD", "").strip() == "0":
        args += ["--render-thread", "safe"]   # Godot's separate render thread off (scripts/run.py --no-render-thread)
    args += shlex.split(env.get("GODOT_ARGS", ""))
    if hardware(env) == "proc":
        args += ["--", "--proc-dmd"] if "--" not in args else ["--proc-dmd"]
    return args


def godot_command(env, godot=None):
    import toolchain as tc
    exe = godot or env.get("GODOT") or tc.godot_path()
    return [exe, "--path", tc.GAME] + godot_args(env)


def mpf_command(env):
    import run
    import toolchain as tc
    return tc.mpf_command() + run.mpf_args(hardware(env), text_ui=truthy(env.get("MPF_TEXT_UI")),
                                         free_play=truthy(env["FREE_PLAY"]) if env.get("FREE_PLAY") else None,
                                         machine=machine(env), fiber_optics=truthy(env.get("TRON_FIBER_OPTICS")))


def monitor_command():
    import toolchain as tc
    return tc.mpf_command() + ["monitor"]


def display_env(env, key):
    """env with DISPLAY taken from env[key] when that is set (a window on another X display or screen)."""
    out = dict(env)
    if env.get(key):
        out["DISPLAY"] = env[key]
    return out


def check_display(env):
    if not (env.get("DISPLAY") or env.get("WAYLAND_DISPLAY")):
        raise SystemExit("no DISPLAY: run through docker/tron.sh, or export DISPLAY and allow the container on your "
                         "X server (xhost +SI:localuser:$USER); docker/README.md")


def wait_for_port(port, timeout, label):
    """Wait until something listens on port (in this network namespace). Never connects: GMC quits when a
    client hangs up."""
    import run
    say("waiting for {} on port {}".format(label, port))
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if run.port_in_use(port):
            return
        time.sleep(0.5)
    raise SystemExit("{} did not open port {} within {} s".format(label, port, timeout))


def workspace_ready(root=WORKSPACE):
    marks = [os.path.join("assets", "mpf_package"), os.path.join("game", "addons", "mpf-gmc", "plugin.cfg"),
             os.path.join("game", "config", "rom"), os.path.join("game", "sounds"), os.path.join("game", ".godot")]
    missing = [m for m in marks if not os.path.exists(os.path.join(root, m))]
    if not missing:
        import toolchain as tc
        stale = tc.media_stale(root)
        if stale:                    # a pull changed the generators or the assets: setup runs again
            missing.append("current media ({})".format(stale))
    return missing


def exec_(cmd, env=None, cwd=None):
    say("$ " + " ".join(shlex.quote(c) for c in cmd))
    if cwd:
        os.chdir(cwd)
    os.execvpe(cmd[0], cmd, env if env is not None else os.environ)


def main(argv=None, env=None):
    argv = sys.argv[1:] if argv is None else argv
    env = dict(os.environ if env is None else env)
    role = argv[0] if argv else "shell"
    rest = argv[1:]
    import toolchain as tc
    timeout = float(env.get("TRON_WAIT_SECONDS", "180"))

    if role == "setup":
        if not os.path.isdir(os.path.join(WORKSPACE, "assets", "mpf_package")):
            raise SystemExit("assets/ is empty: on the host, run `git submodule update --init --depth 1 assets` "
                             "(or clone with --recurse-submodules)")
        missing = workspace_ready()
        if not missing and not truthy(env.get("TRON_FORCE_SETUP")):
            say("workspace ready (TRON_FORCE_SETUP=1 redoes the setup)")
            return 0
        if missing:
            say("setting up the workspace, missing: " + ", ".join(missing))
        return subprocess.call([tc.python(), os.path.join(WORKSPACE, "scripts", "setup.py"), "--monitor"] + rest,
                               cwd=WORKSPACE)
    if role == "godot":
        import gmc_patch
        gmc_patch.patch()               # GMC 1.0.0 drops BCP messages split across reads (sounds, music)
        genv = display_env(env, "DMD_DISPLAY")
        check_display(genv)
        exec_(godot_command(genv) + rest, genv, WORKSPACE)
    if role == "mpf":
        wait_for_port(tc.BCP_PORT, timeout, "GMC (godot service)")
        exec_(mpf_command(env) + rest, env, tc.GAME)
    if role == "monitor":
        import run
        run.monitor_settings()
        menv = display_env(env, "MONITOR_DISPLAY")
        check_display(menv)
        wait_for_port(tc.MONITOR_PORT, timeout, "MPF (mpf service)")
        exec_(monitor_command() + rest, menv, tc.GAME)
    if role == "render-check":
        env.pop("DISPLAY", None)
        env.pop("WAYLAND_DISPLAY", None)
        exec_([tc.python(), os.path.join(WORKSPACE, "scripts", "render_check.py")] + (rest or ["15"]), env, WORKSPACE)
    if role == "test":
        exec_([tc.python(), "-m", "pytest", "-q", "tests"] + rest, env, WORKSPACE)
    if role == "shell":
        exec_(rest or ["bash"], env, WORKSPACE)
    raise SystemExit("unknown role {!r}: setup, godot, mpf, monitor, render-check, test or shell".format(role))


if __name__ == "__main__":
    sys.exit(main())
