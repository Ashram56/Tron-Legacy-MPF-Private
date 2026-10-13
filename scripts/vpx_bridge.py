#!/usr/bin/env python3
"""TronMPF.Controller: the COM object a Visual Pinball X table uses in place of VPinMAME.Controller, run by MPF.

Windows, once (as Administrator, with this repo's venv; `pip install pywin32` first):
    .venv\\Scripts\\python scripts\\vpx_bridge.py --register      (--unregister removes it)
Then the table script (scripts/vpx_table.py writes it) does
    Set Controller = CreateObject("TronMPF.Controller") ... Controller.Run
and every Controller call becomes an MPF "vpcom_bridge" BCP command on MPF's BCP server (127.0.0.1:5051), which
MPF's virtual_pinball platform answers (game/config/hw_vpx.yaml, game/tron/vpx_hardware.py).

Run() connects to MPF. When nothing listens on the port it starts the game itself, in a new console:
`python scripts/run.py --hw vpx` (Godot for the DMD and sound, then MPF), and waits for it. Starting run.py
yourself first is quicker and shows MPF's log from the start. Settings (environment variables):
    TRON_MPF_HOST / TRON_MPF_PORT   where MPF's BCP server is (default 127.0.0.1 / 5051)
    TRON_VPX_LAUNCH=0               never start the game, only connect
    TRON_VPX_RUN_ARGS               extra run.py arguments, e.g. "--dmd classic --dmd-size 1280x320"
Log: game/logs/vpx_bridge.log.

Any OS, without VPX:  python scripts/vpx_bridge.py --check   connects to a running `run.py --hw vpx` (or starts
it) and drives it the way the table does: loads the trough, presses start, plunges, reads lamps and coils.

The same COM interface as missionpinball/mpf-vpcom-bridge (MIT), with what this table needs on top: Run()
accepts VPX's window handle (the table calls `.Run GetPlayerHWnd`), starts MPF, unknown properties
(Hidden, SolMask, Games().Settings) are accepted, and "nothing changed" is returned as Empty, as VPinMAME does.
"""
import argparse
import logging
import os
import shlex
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LOG_DIR = os.path.join(ROOT, "game", "logs")
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5051
LAUNCH_TIMEOUT = 300        # first run after a pull regenerates the media
PROGID = "TronMPF.Controller"
CLSID = "{6B1C0E3A-54F2-4A57-9C3E-7D2B1F0A5E11}"

try:            # Windows with pywin32: the COM server. Elsewhere only --check is available.
    import pythoncom
    import winerror
    from win32com.server.exception import COMException
    from win32com.server.util import wrap
except ImportError:
    pythoncom = winerror = wrap = None

    class COMException(Exception):
        def __init__(self, desc="", scode=None):
            super().__init__(desc)
            self.description = desc

sys.path.insert(0, HERE)
log = logging.getLogger("vpx_bridge")


def setup_logging(path=None):
    if log.handlers:
        return
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        handler = logging.FileHandler(path or os.path.join(LOG_DIR, "vpx_bridge.log"), mode="w", encoding="utf-8")
    except OSError:
        handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)


# ---------------------------------------------------------------------- BCP
def _bcp():
    """MPF's own BCP encoder/decoder (the venv has MPF)."""
    from mpf.core.bcp.bcp_socket_client import decode_command_string, encode_command_string
    return encode_command_string, decode_command_string


class BridgeError(Exception):
    pass


class MpfLink:

    """One BCP connection to MPF's server; call() sends a vpcom_bridge command and returns its result."""

    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT):
        self.host, self.port = host, port
        self.sock = None
        self.buffer = b""
        self.encode, self.decode = _bcp()

    def connect(self, timeout=5.0):
        sock = socket.create_connection((self.host, self.port), timeout=timeout)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)     # one small request, one small answer
        sock.settimeout(None)
        self.sock = sock

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None

    def send(self, command, **params):
        self.sock.sendall((self.encode(command, **params) + "\n").encode("utf-8"))

    def read_command(self):
        while b"\n" not in self.buffer:
            data = self.sock.recv(65536)
            if not data:
                raise BridgeError("MPF closed the connection")
            self.buffer += data
        line, _, self.buffer = self.buffer.partition(b"\n")
        return self.decode(line.decode("utf-8").strip())

    def call(self, subcommand, **params):
        if not self.sock:
            raise BridgeError("not connected to MPF (Controller.Run was not called or failed)")
        params["subcommand"] = subcommand
        self.send("vpcom_bridge", **params)
        while True:
            command, kwargs = self.read_command()
            if command == "vpcom_bridge_response":
                break
            if command == "goodbye":
                raise BridgeError("MPF said goodbye")
            # anything else MPF sends every client (hello, monitor events) is not for us
        if "error" in kwargs:
            raise BridgeError("MPF: {} ({})".format(kwargs["error"], subcommand))
        return kwargs.get("result")


def port_open(host, port):
    try:
        socket.create_connection((host, port), timeout=1.0).close()
        return True
    except OSError:
        return False


def launch_game():
    """Start `run.py --hw vpx` in its own console window; returns the Popen."""
    import toolchain as tc
    python = tc.python()
    if not os.path.exists(python):
        python = sys.executable.replace("pythonw.exe", "python.exe")
    cmd = [python, os.path.join(HERE, "run.py"), "--hw", "vpx"] + shlex.split(os.environ.get("TRON_VPX_RUN_ARGS", ""))
    kw = {"cwd": ROOT}
    if os.name == "nt":
        kw["creationflags"] = subprocess.CREATE_NEW_CONSOLE
    log.info("starting the game: %s", " ".join(cmd))
    return subprocess.Popen(cmd, **kw)


def connect_or_launch(host, port, launch=True, timeout=LAUNCH_TIMEOUT):
    """An MpfLink connected to MPF, starting the game first if nothing listens and launch is on."""
    proc = None
    if not port_open(host, port) and launch and host in ("127.0.0.1", "localhost", "::1"):
        proc = launch_game()
    end = time.monotonic() + (timeout if proc else 5)
    while True:
        link = MpfLink(host, port)
        try:
            link.connect()
            return link, proc
        except OSError as e:
            if time.monotonic() > end or (proc and proc.poll() is not None):
                raise BridgeError("cannot reach MPF at {}:{} ({}){}".format(
                    host, port, e, "; the game exited, see its console" if proc and proc.poll() is not None
                    else "; start it with: python scripts/run.py --hw vpx"))
            time.sleep(0.5)


def changes(result):
    """VPinMAME returns Empty when nothing changed and a 2-D array (n x 2) otherwise. pywin32 turns a list of
    equal-length lists into a 2-D SAFEARRAY, and None into Empty."""
    if not result:
        return None
    return [[int(n), int(v)] for n, v in result]


# ---------------------------------------------------------------------- COM objects
class Settings:
    _public_methods_ = []
    _public_attrs_ = ["Value"]

    def __init__(self):
        self.values = {}

    def Value(self, name):
        return self.values.get(str(name).lower(), 0)

    def SetValue(self, name, value):
        self.values[str(name).lower()] = value


class Game:
    _public_methods_ = []
    _public_attrs_ = ["Settings"]

    def __init__(self, settings):
        self._settings = settings

    def Settings(self):
        return wrap(self._settings) if wrap else self._settings


class Controller:

    """VPinMAME.Controller's interface, as far as VPX's core.vbs, sam.vbs and the Tron table use it."""

    _reg_progid_ = PROGID
    _reg_clsid_ = CLSID
    _reg_desc_ = "Tron Legacy MPF bridge for Visual Pinball X (VPinMAME.Controller stand-in)"
    _reg_clsctx_ = pythoncom.CLSCTX_LOCAL_SERVER if pythoncom else 4
    _public_methods_ = ["Run", "Stop", "PrintGlobal", "PulseSW", "IsCoilActive", "ShowOptsDialog",
                        "ShowPathesDialog", "ShowAboutDialog", "CheckROMS"]
    _public_attrs_ = ["Version", "GameName", "Games", "SplashInfoLine", "ShowTitle", "ShowFrame", "ShowDMDOnly",
                      "HandleMechanics", "HandleKeyboard", "Hidden", "DIP", "Switch", "Lamp", "Solenoid", "Mech",
                      "GetMech", "Pause", "SolMask", "ChangedSolenoids", "ChangedLamps", "ChangedGIStrings",
                      "ChangedLEDs", "ChangedFlashers", "HardwareRules", "Running", "TableName", "B2SName",
                      "LockDisplay", "DoubleSize", "Antialias"]
    _readonly_attrs_ = ["Version", "ChangedSolenoids", "ChangedLamps", "ChangedGIStrings", "ChangedLEDs",
                        "ChangedFlashers", "HardwareRules", "Running"]

    Version = "03060000"        # core.vbs turns modulated solenoids on (SolMask(2)) from 3.6
    GameName = "trn_174h"
    SplashInfoLine = ""
    ShowTitle = ShowFrame = ShowDMDOnly = HandleKeyboard = Hidden = LockDisplay = DoubleSize = Antialias = False
    HandleMechanics = True
    DIP = 0
    Pause = False
    TableName = B2SName = ""

    def __init__(self):
        setup_logging()
        self.link = None
        self.proc = None
        self.solmask = {}
        self.settings = Settings()
        self.lamps = {}
        self.solenoids = {}

    # -- connection
    def Run(self, *args):
        """VPinMAME: Run(hWnd, ...). Also accepts Run(host) or Run(host, port) as mpf-vpcom-bridge does."""
        host = os.environ.get("TRON_MPF_HOST", DEFAULT_HOST)
        port = int(os.environ.get("TRON_MPF_PORT", DEFAULT_PORT))
        if args and isinstance(args[0], str) and args[0] and not args[0].isdigit():
            host = args[0]
            if len(args) > 1 and str(args[1]).isdigit():
                port = int(args[1])
        launch = os.environ.get("TRON_VPX_LAUNCH", "1") != "0"
        log.info("Run%r: connecting to MPF at %s:%s", args, host, port)
        try:
            self.link, self.proc = connect_or_launch(host, port, launch)
            self.link.call("start")
        except (BridgeError, OSError) as e:
            log.error("Run failed: %s", e)
            raise COMException(desc="Tron MPF bridge: {}".format(e), scode=winerror.E_FAIL if winerror else None)
        log.info("connected, MPF started the machine")
        return True

    @property
    def Running(self):
        return self.link is not None

    def Stop(self):
        """The table closed (core.vbs calls it from Table_Exit). A game this bridge started quits with it."""
        launched = bool(self.proc and self.proc.poll() is None)
        log.info("Stop%s", ": quitting the game this bridge started" if launched else "")
        if self.link:
            try:
                self.link.call("stop", quit=launched)
            except (BridgeError, OSError):
                pass
            self.link.close()
            self.link = None
        if launched:
            try:
                self.proc.wait(20)          # run.py stops Godot once MPF has quit
            except subprocess.TimeoutExpired:
                self.proc.terminate()
        return True

    def _call(self, subcommand, **params):
        if not self.link:
            raise COMException(desc="Tron MPF bridge: not connected (Controller.Run)",
                               scode=winerror.E_FAIL if winerror else None)
        try:
            return self.link.call(subcommand, **params)
        except (BridgeError, OSError) as e:
            log.error("%s %s: %s", subcommand, params, e)
            raise COMException(desc="Tron MPF bridge: {}".format(e), scode=winerror.E_FAIL if winerror else None)

    # -- switches
    def Switch(self, number):
        return bool(self._call("get_switch", number=int(number)))

    def SetSwitch(self, number, value):
        self._call("set_switch", number=int(number), value=bool(value))

    def PulseSW(self, number):
        self._call("pulsesw", number=int(number))
        return True

    # -- outputs
    def ChangedSolenoids(self):
        result = changes(self._call("changed_solenoids"))
        for n, v in result or ():
            self.solenoids[n] = v
        return result

    def ChangedLamps(self):
        result = changes(self._call("changed_lamps"))
        for n, v in result or ():
            self.lamps[n] = v
        return result

    def ChangedGIStrings(self):
        return None             # MPF has no GI strings here; the table turns its GI on at start

    def ChangedLEDs(self, *args):
        return None

    def ChangedFlashers(self):
        return None

    def Lamp(self, number):
        return bool(self.lamps.get(int(number), 0))

    def Solenoid(self, number):
        return bool(self.solenoids.get(int(number), 0))

    def HardwareRules(self):
        return None             # tron/vpx_hardware.py plays MPF's hardware rules itself

    def IsCoilActive(self, number):
        return bool(self._call("get_coilactive", number=str(int(number))))

    def Mech(self, number):
        return 0

    def SetMech(self, number, value):
        pass

    def GetMech(self, number):
        return 0

    # -- settings the table writes and VPinMAME keeps
    def SolMask(self, index):
        return self.solmask.get(int(index), 0)

    def SetSolMask(self, index, value):
        self.solmask[int(index)] = value

    def Games(self, name=None):
        game = Game(self.settings)
        return wrap(game) if wrap else game

    def PrintGlobal(self):
        return True

    def ShowOptsDialog(self, *args):
        return True

    ShowPathesDialog = ShowAboutDialog = ShowOptsDialog

    def CheckROMS(self, *args):
        return True


def register(unregister=False):
    if not pythoncom:
        raise SystemExit("the COM server needs Windows and pywin32: .venv\\Scripts\\python -m pip install pywin32")
    from win32com.server.register import UseCommandLine
    sys.argv = [sys.argv[0]] + (["--unregister"] if unregister else [])
    UseCommandLine(Controller)


# ---------------------------------------------------------------------- --check
def check(seconds=20.0):
    """Drive a running game like the table does; print what comes back. Exit code 0 when MPF answered."""
    setup_logging()
    log.addHandler(logging.StreamHandler(sys.stdout))
    c = Controller()
    c.Run(0)
    seen_sol, seen_lamps = {}, {}

    def poll(t):
        end = time.monotonic() + t
        while time.monotonic() < end:
            for n, v in c.ChangedSolenoids() or ():
                seen_sol[n] = seen_sol.get(n, 0) + (1 if v else 0)
            for n, v in c.ChangedLamps() or ():
                seen_lamps[n] = v
            time.sleep(0.01)

    for sw in (18, 19, 20, 21):             # bsTrough.Balls = 4
        c.SetSwitch(sw, True)
    c.SetSwitch(52, True)                   # the table's init: 3-bank down
    poll(3)
    print("lamps on after start-up:", sorted(n for n, v in seen_lamps.items() if v))
    c.SetSwitch(65, True)                   # coin (MPF ignores it on free play)
    c.SetSwitch(65, False)
    c.SetSwitch(16, True)                   # START
    poll(0.2)
    c.SetSwitch(16, False)
    poll(3)
    print("solenoids fired:", sorted(n for n, v in seen_sol.items() if v and n != 33))
    print("flippers enabled (solenoid 33):", c.solenoids.get(33) == 255)
    if seen_sol.get(1):                     # trough kicker: the ball moves to the shooter lane
        c.SetSwitch(21, False)
        c.SetSwitch(23, True)
        poll(1)
        c.SetSwitch(23, False)              # plunged
        c.SetSwitch(12, True)
        c.SetSwitch(12, False)              # zen rollover
    c.SetSwitch(84, True)
    poll(0.1)
    print("left flipper coil with the button held:", c.solenoids.get(15))
    c.SetSwitch(84, False)
    c.SetSwitch(66, True)                   # unknown to MPF: ignored, no error
    poll(max(0.0, seconds - 7.5))
    print("lamps on now:", sorted(n for n, v in c.lamps.items() if v))
    c.Stop()
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--register", action="store_true", help="register TronMPF.Controller (Windows, as Administrator)")
    g.add_argument("--unregister", action="store_true", help="remove the registration")
    g.add_argument("--check", action="store_true", help="drive a running game the way the table does (any OS)")
    p.add_argument("--seconds", type=float, default=20.0, help="--check: how long to run")
    args = p.parse_args(argv)
    if args.check:
        return check(args.seconds)
    register(args.unregister)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
