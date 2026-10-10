"""Per-OS paths and download URLs of scripts/toolchain.py, and scripts/setup.py's plan, for Windows, macOS and
Linux, whatever OS runs the tests."""
import contextlib
import io
import os
import socket
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import gmc_patch  # noqa: E402
import run  # noqa: E402
import setup  # noqa: E402
import toolchain as tc  # noqa: E402

RELEASES = "https://github.com/godotengine/godot/releases/download/4.6.3-stable/"


class TestHost(unittest.TestCase):

    def test_os_names(self):
        for system, name in [("Windows", "windows"), ("Darwin", "macos"), ("Linux", "linux"), ("linux", "linux")]:
            self.assertEqual(name, tc.host_os(system))
        with self.assertRaises(SystemExit):
            tc.host_os("SunOS")

    def test_arch_names(self):
        for machine, name in [("AMD64", "x86_64"), ("x86_64", "x86_64"), ("arm64", "arm64"), ("aarch64", "arm64")]:
            self.assertEqual(name, tc.host_arch(machine))
        with self.assertRaises(SystemExit):
            tc.host_arch("i386")

    def test_this_host_is_supported(self):
        self.assertIn(tc.host_os(), ("windows", "macos", "linux"))


class TestVenv(unittest.TestCase):

    @mock.patch.dict(os.environ, {"TRON_VENV": ""})
    def test_layout(self):
        venv = os.path.join(ROOT, ".venv")
        self.assertEqual(os.path.join(venv, "Scripts", "python.exe"), tc.venv_python("windows"))
        self.assertEqual(os.path.join(venv, "Scripts", "mpf.exe"), tc.venv_exe("mpf", "windows"))
        for os_name in ("macos", "linux"):
            self.assertEqual(os.path.join(venv, "bin", "python"), tc.venv_python(os_name))
            self.assertEqual(os.path.join(venv, "bin", "mpf"), tc.venv_exe("mpf", os_name))

    def test_env_override(self):
        """The Docker image's venv lives outside the bind-mounted repository."""
        with mock.patch.dict(os.environ, {"TRON_VENV": "/opt/venv"}):
            self.assertEqual("/opt/venv", tc.venv_dir())
            self.assertEqual(os.path.join("/opt/venv", "bin", "python"), tc.venv_python("linux"))
            self.assertEqual(os.path.join("/tmp", ".venv"), tc.venv_dir("/tmp"))


class TestGodot(unittest.TestCase):
    CASES = [  # os, arch, zip, executable in tools/godot/
        ("windows", "x86_64", "Godot_v4.6.3-stable_win64.exe.zip", ["Godot_v4.6.3-stable_win64.exe"]),
        ("windows", "arm64", "Godot_v4.6.3-stable_windows_arm64.exe.zip", ["Godot_v4.6.3-stable_windows_arm64.exe"]),
        ("macos", "x86_64", "Godot_v4.6.3-stable_macos.universal.zip", ["Godot.app", "Contents", "MacOS", "Godot"]),
        ("macos", "arm64", "Godot_v4.6.3-stable_macos.universal.zip", ["Godot.app", "Contents", "MacOS", "Godot"]),
        ("linux", "x86_64", "Godot_v4.6.3-stable_linux.x86_64.zip", ["Godot_v4.6.3-stable_linux.x86_64"]),
        ("linux", "arm64", "Godot_v4.6.3-stable_linux.arm64.zip", ["Godot_v4.6.3-stable_linux.arm64"]),
    ]

    def test_urls_and_paths(self):
        for os_name, arch, asset, exe in self.CASES:
            with self.subTest(os=os_name, arch=arch):
                self.assertEqual(asset, tc.godot_asset(os_name, arch))
                self.assertEqual(RELEASES + asset, tc.godot_url(os_name, arch))
                self.assertEqual(os.path.join(ROOT, "tools", "godot", *exe), tc.godot_path(os_name, arch))

    def test_env_override(self):
        with mock.patch.dict(os.environ, {"GODOT": "/opt/godot/godot"}):
            self.assertEqual("/opt/godot/godot", tc.godot_path())
            self.assertEqual("/opt/godot/godot", tc.godot_command("--import")[0])

    def test_virtual_display(self):
        self.assertTrue(tc.needs_virtual_display("linux", {}))
        self.assertFalse(tc.needs_virtual_display("linux", {"DISPLAY": ":0"}))
        self.assertFalse(tc.needs_virtual_display("linux", {"WAYLAND_DISPLAY": "wayland-0"}))
        self.assertFalse(tc.needs_virtual_display("windows", {}))
        self.assertFalse(tc.needs_virtual_display("macos", {}))


class TestSetupPlan(unittest.TestCase):
    """setup.py --os/--arch prints the plan for that host and changes nothing."""

    def plan(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mock.patch.object(setup.subprocess, "run") as sp, \
                mock.patch.object(setup, "download") as dl:
            self.assertEqual(0, setup.main(list(args)))
        sp.assert_not_called()
        dl.assert_not_called()
        return out.getvalue()

    def test_each_os(self):
        for os_name, arch, asset, exe in TestGodot.CASES:
            with self.subTest(os=os_name, arch=arch):
                text = self.plan("--os", os_name, "--arch", arch)
                self.assertIn("(dry run)", text)
                self.assertIn(RELEASES + asset, text)
                self.assertIn(os.path.join("tools", "godot", *exe), text)
                self.assertIn(tc.venv_python(os_name), text)
                self.assertIn(tc.GMC_ZIP, text)
                self.assertIn("gen_media.py", text)

    def test_monitor_and_skip(self):
        text = self.plan("--dry-run", "--skip-godot")             # MPF Monitor is in by default
        self.assertIn("mpf-monitor==" + tc.MPF_MONITOR_VERSION, text)
        self.assertIn("mpf-monitor==", self.plan("--dry-run", "--monitor", "--skip-godot"))
        self.assertNotIn("mpf-monitor==", self.plan("--dry-run", "--no-monitor", "--skip-godot"))
        self.assertNotIn("== Godot", text)
        self.assertNotIn(tc.godot_url(), text)


class TestUnpack(unittest.TestCase):

    def zip_of(self, files):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for name, body in files.items():
                z.writestr(name, body)
        return buf.getvalue()

    def test_gmc_folder(self):
        """GitHub's tag zip: mpf-gmc-1.0.0/addons/mpf-gmc/... -> game/addons/mpf-gmc/..."""
        data = self.zip_of({"mpf-gmc-1.0.0/README.md": "x", "mpf-gmc-1.0.0/addons/mpf-gmc/plugin.cfg": "[plugin]",
                            "mpf-gmc-1.0.0/addons/mpf-gmc/scripts/bcp_server.gd": "extends Node"})
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(2, setup.extract_folder(data, "mpf-gmc-1.0.0/addons/mpf-gmc/", tmp))
            self.assertTrue(os.path.isfile(os.path.join(tmp, "plugin.cfg")))
            self.assertTrue(os.path.isfile(os.path.join(tmp, "scripts", "bcp_server.gd")))
            self.assertFalse(os.path.exists(os.path.join(tmp, "README.md")))

    def test_godot_zip_keeps_exec_bit(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            info = zipfile.ZipInfo("Godot_v4.6.3-stable_linux.x86_64")
            info.external_attr = 0o755 << 16
            z.writestr(info, "ELF")
        with tempfile.TemporaryDirectory() as tmp:
            setup.unzip(buf.getvalue(), tmp, "linux")
            exe = os.path.join(tmp, "Godot_v4.6.3-stable_linux.x86_64")
            self.assertTrue(os.path.isfile(exe))
            if os.name != "nt":
                self.assertTrue(os.access(exe, os.X_OK))


class TestRun(unittest.TestCase):

    def test_port_in_use(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
            s.listen()
            self.assertTrue(run.port_in_use(port))
        self.assertFalse(run.port_in_use(port))

    @unittest.skipUnless(socket.has_ipv6, "no IPv6")
    def test_port_in_use_ipv6_listener(self):
        # Godot's TCPServer listens on "*": an IPv6 socket, which on Windows leaves the IPv4 port free
        try:
            s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
            s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            s.bind(("::1", 0))
        except OSError:
            self.skipTest("IPv6 loopback not available")
        with s:
            port = s.getsockname()[1]
            s.listen()
            self.assertTrue(run.port_in_use(port))

    def test_scenario_path(self):
        # this repo's scenarios/ first, then the asset repo's traces (by name, as live_scenario.py finds them)
        self.assertEqual(run.scenario_path("full_game_to_portal"),
                         os.path.join(ROOT, "scenarios", "full_game_to_portal.txt"))
        self.assertEqual(run.scenario_path("game_flow"), "game_flow")
        self.assertTrue(os.path.isabs(run.scenario_path("my_game.txt")))   # MPF runs in game/

    def test_wait_for_port_log_marker(self):
        with tempfile.TemporaryDirectory() as d:
            log = os.path.join(d, "godot.log")
            with open(log, "w") as f:
                f.write("INFO : GMCServer : GMC listening on port 5050\n")
            with socket.socket() as s:      # a free port, so only the log can say ready
                s.bind(("127.0.0.1", 0))
                port = s.getsockname()[1]
            self.assertTrue(run.wait_for_port(port, [], 1, log, "GMC listening on port"))
            self.assertFalse(run.wait_for_port(port, [], 0.5, log, "not there"))
            self.assertIn("GMC listening", run.log_tail(log))

    def test_monitor_settings_copied_once(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "monitor"))
            with open(os.path.join(d, "monitor", "settings.ini.default"), "w") as f:
                f.write("[settings]\n")
            with mock.patch.object(run.tc, "GAME", d):
                run.monitor_settings()
                with open(os.path.join(d, "monitor", "settings.ini"), "w") as f:
                    f.write("mine")
                run.monitor_settings()
            with open(os.path.join(d, "monitor", "settings.ini")) as f:
                self.assertEqual("mine", f.read())
        self.assertTrue(os.path.exists(os.path.join(run.tc.GAME, "monitor", "settings.ini.default")))

    def test_ensure_monitor(self):
        """run.py --monitor in a workspace without MPF Monitor installs it rather than failing."""
        ok, missing = mock.Mock(returncode=0), mock.Mock(returncode=1)
        with mock.patch.object(run.subprocess, "run", return_value=ok), \
                mock.patch.object(setup.Setup, "venv") as venv:
            run.ensure_monitor()
        venv.assert_not_called()
        with mock.patch.object(run.subprocess, "run", return_value=missing), \
                mock.patch.object(setup.Setup, "venv") as venv, contextlib.redirect_stdout(io.StringIO()):
            run.ensure_monitor()
        venv.assert_called_once_with()

    def test_mpf_args(self):
        self.assertEqual(["game", ".", "-c", "config,hw_virtual,free_play", "-t"], run.mpf_args("virtual"))
        self.assertEqual(["game", ".", "-c", "config,hw_virtual", "-t"], run.mpf_args("virtual", free_play=False))
        self.assertEqual(["game", ".", "-c", "config,hw_proc"], run.mpf_args("proc", text_ui=True))
        self.assertEqual(["game", ".", "-c", "config,hw_virtual_le", "-t", "-X"], run.mpf_args("virtual", "zuse"))

    def test_mpf_args_machine(self):
        """Pro by default; the VPW table and the ROM traces are the LE."""
        self.assertEqual("config,hw_proc_le", run.mpf_args("proc", machine="le")[3])
        self.assertEqual("config,hw_proc,fiber_optics", run.mpf_args("proc", fiber_optics=True)[3])
        self.assertEqual("config,hw_vpx,free_play", run.mpf_args("vpx")[3])
        self.assertEqual("config,hw_vpx_pro,free_play", run.mpf_args("vpx", machine="pro")[3])
        self.assertEqual("config,hw_virtual,free_play", run.mpf_args("virtual", machine="pro")[3])
        for name in ("hw_proc_le", "hw_vpx_pro", "hw_virtual_le", "fiber_optics"):
            self.assertTrue(os.path.exists(os.path.join(ROOT, "game", "config", name + ".yaml")), name)

    def test_xvfb_only_without_display(self):
        with mock.patch.dict(os.environ, {"GODOT": sys.executable}):
            self.assertEqual(sys.executable, run.godot_command([], virtual_display=False)[0])
            with mock.patch.object(run.shutil, "which", return_value="/usr/bin/xvfb-run"):
                self.assertEqual("xvfb-run", run.godot_command([], virtual_display=True)[0])


class TestMediaStale(unittest.TestCase):
    """The generated media (git-ignored) follow the generators and the assets: after a pull that changes
    them, run.py and the docker setup make and import them again. Play test 2: the ZUSE / TRON letters,
    the SOS stage text and the fixed layouts were in the code, but a workspace kept the slides generated
    before (the capture's letters, all hollow; SHOOT FLYNNS ARCADE on every stage)."""

    def test_stamp_follows_inputs_and_import(self):
        with tempfile.TemporaryDirectory() as root:
            for rel in tc.MEDIA_INPUTS:
                os.makedirs(os.path.join(root, os.path.dirname(rel)), exist_ok=True)
                with open(os.path.join(root, rel), "w") as f:
                    f.write("v1")
            letters = os.path.join(root, "game", "media", "dmd", "deff_091")
            os.makedirs(letters)
            png = os.path.join(letters, "solid0.png")
            open(png, "w").close()
            self.assertIn("no stamp", tc.media_stale(root))             # never generated with a stamp
            tc.write_media_stamp(root)
            self.assertIn("not imported", tc.media_stale(root))         # gen_media without the Godot import
            open(png + ".import", "w").close()
            self.assertIsNone(tc.media_stale(root))
            with open(os.path.join(root, "scripts", "rom_layout.py"), "w") as f:
                f.write("v2")                                           # a pull changed a generator
            self.assertIn("changed", tc.media_stale(root))

    def test_run_refreshes_stale_media(self):
        with mock.patch.object(tc, "media_stale", return_value="changed"), \
                mock.patch.object(setup, "refresh_media") as refresh, \
                mock.patch.object(run, "port_in_use", return_value=True), \
                mock.patch.object(run.gmc_patch, "patch"), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):                         # stops at the busy port, after the refresh
                run.run("virtual")
        refresh.assert_called_once_with()


class TestGmcPatch(unittest.TestCase):

    def test_patch_unpatched_gmc_once(self):
        src = tc.GMC_DIR
        if not os.path.exists(os.path.join(src, "plugin.cfg")):
            self.skipTest("GMC not installed")
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "scripts"))
            open(os.path.join(d, "plugin.cfg"), "w").close()
            for rel, old, new in gmc_patch.EDITS:      # rebuild the stock files from the installed (maybe patched) ones
                path = os.path.join(d, *rel.split("/"))
                if not os.path.exists(path):
                    with open(os.path.join(src, *rel.split("/")), encoding="utf-8", newline="") as f:
                        text = f.read()
                    with open(path, "w", encoding="utf-8", newline="") as f:
                        f.write(text)
            for rel, old, new in reversed(gmc_patch.EDITS):
                path = os.path.join(d, *rel.split("/"))
                with open(path, encoding="utf-8", newline="") as f:
                    text = f.read()
                if new in text:
                    with open(path, "w", encoding="utf-8", newline="") as f:
                        f.write(text.replace(new, old))
            self.assertEqual("patched", gmc_patch.patch(d, quiet=True))
            self.assertEqual("in place", gmc_patch.patch(d, quiet=True))
            with open(os.path.join(d, "scripts", "bcp_server.gd"), encoding="utf-8") as f:
                self.assertIn("_rx_partial = data.substr(cut + 1)", f.read())
        self.assertEqual("missing", gmc_patch.patch(os.path.join(src, "nowhere")))


if __name__ == "__main__":
    unittest.main()
