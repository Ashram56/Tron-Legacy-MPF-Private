"""The prerequisite installers (scripts/install/), the Docker entry point and compose files (docker/), and MPF
Monitor's missing window layouts (setup.install_monitor_ui). Shell scripts run in --dry-run mode only."""
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import setup  # noqa: E402
import toolchain as tc  # noqa: E402

INSTALL = os.path.join(ROOT, "scripts", "install")
DOCKER = os.path.join(ROOT, "docker")
BASH = shutil.which("bash")
POSIX = os.name == "posix"


def load_entrypoint():
    spec = importlib.util.spec_from_file_location("tron_entrypoint", os.path.join(DOCKER, "entrypoint.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sh(args, env=None):
    full = dict(os.environ, **(env or {}))
    return subprocess.run([BASH] + args, capture_output=True, text=True, env=full, timeout=120, cwd=ROOT)


@unittest.skipUnless(BASH and POSIX, "needs bash on Linux or macOS")
class TestShellScripts(unittest.TestCase):
    SCRIPTS = ["install_prereqs_linux.sh", "install_prereqs_macos.sh", "build_pinproc.sh", "install_jetson_hwdec.sh"]

    def test_syntax(self):
        for name in self.SCRIPTS + [os.path.join("..", "..", "docker", "tron.sh")]:
            with self.subTest(script=name):
                r = sh(["-n", os.path.join(INSTALL, name)])
                self.assertEqual(0, r.returncode, r.stderr)

    def test_jetson_hwdec_skips_other_machines(self):
        if os.path.exists("/etc/nv_tegra_release"):
            self.skipTest("on a Jetson")
        r = sh([os.path.join(INSTALL, "install_jetson_hwdec.sh"), "--dry-run"])
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("not an NVIDIA Jetson", r.stdout)

    def test_jetson_hwdec_plan_on_a_stripped_xavier(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        release = os.path.join(tmp, "nv_tegra_release")
        with open(release, "w") as f:
            f.write("# R35 (release), REVISION: 4.1, GCID: 1, BOARD: t186ref, EABI: aarch64\n")
        with open(os.path.join(tmp, "model"), "w") as f:
            f.write("NVIDIA Jetson Xavier NX Developer Kit\0")
        with open(os.path.join(tmp, "compatible"), "w") as f:
            f.write("nvidia,p3509-0000+p3668-0001\0nvidia,tegra194\0")
        r = sh([os.path.join(INSTALL, "install_jetson_hwdec.sh"), "--dry-run"],
               env={"TRON_ARCH": "aarch64", "TRON_NV_RELEASE": release, "TRON_DEVICE_TREE": tmp})
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertIn("SoC t194, NVIDIA apt release r35.4", r.stdout)
        if os.path.exists("/usr/src/jetson_multimedia_api/include/NvVideoDecoder.h"):
            return  # a real Jetson: nothing is missing
        self.assertIn("nvidia-l4t-jetson-multimedia-api", r.stdout)
        self.assertIn("nvidia-l4t-3d-core", r.stdout)
        # EGL lives in tegra-egl, which the 3d-core package does not add to the loader path
        self.assertIn("tegra-egl/libEGL_nvidia.so.0", r.stdout)
        self.assertIn("aarch64-linux-gnu_EGL.conf: /usr/lib/aarch64-linux-gnu/tegra-egl", r.stdout)
        self.assertIn("scripts/build.sh --no-stubs --install", r.stdout)

    def test_jetson_hwdec_plan_on_an_orin(self):
        """JetPack 6 (AGX Orin, R36.4.3): t234 repo, nvidia/ library folder, installs pinned to 36.4.3."""
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        release = os.path.join(tmp, "nv_tegra_release")
        with open(release, "w") as f:
            f.write("# R36 (release), REVISION: 4.3, GCID: 38968081, BOARD: generic, EABI: aarch64, "
                    "DATE: Wed Jan 8 01:49:37 UTC 2025\n# KERNEL_VARIANT: oot\nTARGET_USERSPACE_LIB_DIR=nvidia\n")
        with open(os.path.join(tmp, "model"), "w") as f:
            f.write("NVIDIA Jetson AGX Orin Developer Kit\0")
        with open(os.path.join(tmp, "compatible"), "w") as f:
            f.write("nvidia,p3737-0000+p3701-0005\0nvidia,p3701-0005\0nvidia,tegra234\0")
        r = sh([os.path.join(INSTALL, "install_jetson_hwdec.sh"), "--dry-run"],
               env={"TRON_ARCH": "aarch64", "TRON_NV_RELEASE": release, "TRON_DEVICE_TREE": tmp,
                    "XDG_CACHE_HOME": tmp})
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertIn("SoC t234, NVIDIA apt release r36.4", r.stdout)
        self.assertIn("l4t-pin.pref: nvidia-l4t-* 36.4.3-*", r.stdout)
        self.assertFalse(os.path.exists(os.path.join(tmp, "tron-legacy-mpf", "l4t-pin.pref")))  # dry run
        if os.path.exists("/usr/src/jetson_multimedia_api/include/NvVideoDecoder.h"):
            return  # a real Jetson: nothing is missing
        self.assertIn("/usr/lib/aarch64-linux-gnu/nvidia/libnvv4l2.so", r.stdout)
        self.assertIn("Dir::Etc::Preferences=", r.stdout)

    def os_release(self, text):
        f = tempfile.NamedTemporaryFile("w", suffix=".os-release", delete=False)
        f.write(text)
        f.close()
        self.addCleanup(os.unlink, f.name)
        return f.name

    def linux_plan(self, os_release, *args):
        return sh([os.path.join(INSTALL, "install_prereqs_linux.sh"), "--dry-run", "--no-setup"] + list(args),
                  env={"TRON_OS_RELEASE": self.os_release(os_release), "DISPLAY": ":0"})

    def test_linux_families(self):
        cases = [('ID=ubuntu\nPRETTY_NAME="Ubuntu 24.04 LTS"\n', "apt", "apt"),
                 ('ID=debian\nPRETTY_NAME="Debian 12"\n', "apt", "apt"),
                 ('ID=linuxmint\nID_LIKE="ubuntu debian"\n', "apt", "apt"),
                 ('ID=fedora\nPRETTY_NAME="Fedora Linux 41"\n', "dnf", "dnf"),
                 ('ID=rocky\nID_LIKE="rhel centos fedora"\n', "dnf", "dnf"),
                 ('ID=arch\nPRETTY_NAME="Arch Linux"\n', "pacman", "pacman"),
                 ('ID=endeavouros\nID_LIKE=arch\n', "pacman", "pacman")]
        for text, family, _ in cases:
            with self.subTest(os_release=text.split("\n")[0]):
                r = self.linux_plan(text, "--monitor", "--proc")
                self.assertEqual(0, r.returncode, r.stdout + r.stderr)
                self.assertIn("({},".format(family), r.stdout)
                self.assertIn("dry run", r.stdout)
                self.assertIn("build_pinproc.sh", r.stdout)
                self.assertIn("99-pinproc.rules", r.stdout)

    def test_linux_unsupported(self):
        r = self.linux_plan('ID=opensuse-tumbleweed\nID_LIKE="opensuse suse"\n')
        self.assertEqual(1, r.returncode)
        self.assertIn("unsupported distribution", r.stderr)

    def test_linux_bad_option(self):
        r = sh([os.path.join(INSTALL, "install_prereqs_linux.sh"), "--bogus"])
        self.assertEqual(2, r.returncode)

    def test_linux_setup_args(self):
        r = sh([os.path.join(INSTALL, "install_prereqs_linux.sh"), "--dry-run", "--", "--skip-media"],
               env={"TRON_OS_RELEASE": self.os_release("ID=debian\n"), "DISPLAY": ":0"})
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertIn("setup.py --dry-run --skip-media", r.stdout)

    def test_macos_plan(self):
        r = sh([os.path.join(INSTALL, "install_prereqs_macos.sh"), "--dry-run"])
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertIn("Python 3.11", r.stdout)
        self.assertIn("setup.py --dry-run", r.stdout)       # MPF Monitor is setup.py's default
        self.assertIn("run.py --monitor", r.stdout)
        r = sh([os.path.join(INSTALL, "install_prereqs_macos.sh"), "--dry-run", "--no-monitor"])
        self.assertIn("setup.py --no-monitor --dry-run", r.stdout)

    def test_standalone_clones(self):
        """Run on its own (bash <(curl ...), README "Install"), an installer clones the repository first;
        run from a clone, it never does."""
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        target = os.path.join(tmp, "tron")
        env = {"TRON_OS_RELEASE": self.os_release("ID=debian\n"), "DISPLAY": ":0", "TRON_DIR": target,
               "TRON_BRANCH": "some-branch", "TRON_REPO": "https://example.invalid/tron.git"}
        for name in ("install_prereqs_linux.sh", "install_prereqs_macos.sh"):
            with self.subTest(script=name):
                alone = os.path.join(tmp, name)
                shutil.copy(os.path.join(INSTALL, name), alone)
                r = sh([alone, "--dry-run"], env=env)
                self.assertEqual(0, r.returncode, r.stdout + r.stderr)
                self.assertIn("git clone --branch some-branch https://example.invalid/tron.git " + target, r.stdout)
                self.assertIn(os.path.join(target, "scripts", "setup.py"), r.stdout)
                os.makedirs(os.path.join(target, ".git"), exist_ok=True)      # no branch: switch to TRON_BRANCH
                r = sh([alone, "--dry-run"], env=env)
                self.assertIn("git -C {} checkout -B some-branch --track origin/some-branch".format(target), r.stdout)
                shutil.rmtree(os.path.join(target, ".git"))
                r = sh([os.path.join(INSTALL, name), "--dry-run"], env=env)
                self.assertEqual(0, r.returncode, r.stdout + r.stderr)
                self.assertNotIn("git clone", r.stdout)
                self.assertIn(os.path.join(ROOT, "scripts", "setup.py"), r.stdout)

    def test_existing_clone_branch_gone(self):
        """An existing clone is pulled while its branch is on the remote, and moved to TRON_BRANCH once that
        branch is deleted there (a merged pull request's branch), instead of failing."""
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        origin, target = os.path.join(tmp, "origin"), os.path.join(tmp, "tron")

        def git(*a, cwd=tmp):
            subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "init.defaultBranch=main"]
                           + list(a), cwd=cwd, check=True, capture_output=True)
        git("init", origin)
        git("commit", "--allow-empty", "-m", "one", cwd=origin)
        git("branch", "feature", cwd=origin)
        git("clone", "--branch", "feature", origin, target)
        for name in ("install_prereqs_linux.sh", "install_prereqs_macos.sh"):
            with self.subTest(script=name):
                alone = os.path.join(tmp, name)
                shutil.copy(os.path.join(INSTALL, name), alone)
                env = {"TRON_OS_RELEASE": self.os_release("ID=debian\n"), "DISPLAY": ":0", "TRON_DIR": target,
                       "TRON_REPO": origin}
                r = sh([alone, "--dry-run"], env=env)
                self.assertIn("git -C {} pull --ff-only".format(target), r.stdout)
        git("branch", "-D", "feature", cwd=origin)
        for name in ("install_prereqs_linux.sh", "install_prereqs_macos.sh"):
            with self.subTest(script=name, branch="gone"):
                r = sh([os.path.join(tmp, name), "--dry-run"], env=env)
                self.assertEqual(0, r.returncode, r.stdout + r.stderr)
                self.assertIn("'feature' is no longer on GitHub", r.stdout)
                self.assertIn("git -C {} checkout -B main --track origin/main".format(target), r.stdout)

    def test_github_auth(self):
        """The token step (run first, so a private repository asks for a token before the long installs): public
        repositories need none, even with a token given; a token that cannot read a private repository stops the install with a clear message, and
        is never printed."""
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        repo = os.path.join(tmp, "repo")
        subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q", repo], check=True)
        subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
                        "--allow-empty", "-m", "one"], check=True)
        for name in ("install_prereqs_linux.sh", "install_prereqs_macos.sh"):
            script = open(os.path.join(INSTALL, name), encoding="utf-8").read()
            funcs = script[script.index("say() {"):script.index("AUTH_DONE=0")]
            public = {"TRON_REPO": repo, "TRON_ASSETS_REPO": repo, "TRON_PUP_REPO": repo}
            for env, code, out in ((public, 0, "public: no token needed"),
                                   # a token from the environment that cannot read anything is not used
                                   (dict(public, GITHUB_TOKEN="secret-token-123"), 0, "public: no token needed"),
                                   (dict(public, TRON_ASSETS_REPO=os.path.join(tmp, "missing"),
                                         TRON_GITHUB_TOKEN="secret-token-123"), 1, "cannot read " + tmp)):
                with self.subTest(script=name, env=sorted(env)):
                    prog = 'DRY=0 YES=1; REPO_URL="$TRON_REPO"\n' + funcs + "github_auth\n"
                    r = subprocess.run(["bash", "-c", prog], capture_output=True, text=True, timeout=60,
                                       env=dict({k: v for k, v in os.environ.items()
                                                 if k not in ("GITHUB_TOKEN", "GH_TOKEN", "TRON_GITHUB_TOKEN")},
                                                HOME=tmp, **env))
                    self.assertEqual(code, r.returncode, r.stdout + r.stderr)
                    self.assertIn(out, r.stdout + r.stderr)
                    self.assertNotIn("secret-token-123", r.stdout + r.stderr)
        r = sh([os.path.join(INSTALL, "install_prereqs_linux.sh"), "--dry-run"],
               env={"TRON_OS_RELEASE": self.os_release("ID=debian\n"), "DISPLAY": ":0"})
        self.assertIn("GitHub access", r.stdout)

    def test_build_pinproc_plan(self):
        r = sh([os.path.join(INSTALL, "build_pinproc.sh"), "--dry-run", "--python", sys.executable,
                "--src", tempfile.gettempdir() + "/tron-pinproc-plan"])
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertIn("-DBUILD_SHARED_LIBS=ON", r.stdout)
        self.assertIn("pip install", r.stdout)

    def test_tron_sh_overlays(self):
        tron = os.path.join(DOCKER, "tron.sh")
        r = sh([tron, "run", "--rm", "test"], env={"TRON_DRY": "1", "TRON_GPU": "0", "TRON_AUDIO": "0",
                                                  "TRON_HW": "virtual"})
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("docker-compose.yml run --rm test", r.stdout)
        self.assertNotIn("proc.yml", r.stdout)
        r = sh([tron], env={"TRON_DRY": "1", "TRON_GPU": "0", "TRON_AUDIO": "0", "TRON_HW": "proc"})
        self.assertIn("-f {} up".format(os.path.join(DOCKER, "proc.yml")), r.stdout)


@unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 (pwsh) is not installed")
class TestWindowsScript(unittest.TestCase):

    def test_parses_and_plans(self):
        script = os.path.join(INSTALL, "install_prereqs_windows.ps1")
        check = ("$e = $null; $t = $null; [void][System.Management.Automation.Language.Parser]::ParseFile("
                 "'{}', [ref]$t, [ref]$e); exit $e.Count".format(script))
        r = subprocess.run(["pwsh", "-NoProfile", "-Command", check], capture_output=True, text=True, timeout=120)
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        r = subprocess.run(["pwsh", "-NoProfile", "-File", script, "-DryRun", "-NoMonitor", "-Proc"],
                           capture_output=True, text=True, timeout=120, cwd=ROOT)
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertIn("Python 3.11", r.stdout)
        self.assertIn("--no-monitor --dry-run", r.stdout)


class TestCompose(unittest.TestCase):

    def load(self, name):
        from ruamel.yaml import YAML
        with open(os.path.join(DOCKER, name), encoding="utf-8") as f:
            return YAML(typ="safe").load(f)

    def test_services(self):
        c = self.load("docker-compose.yml")
        s = c["services"]
        self.assertEqual({"setup", "godot", "mpf", "monitor", "render-check", "test"}, set(s))
        for name in ("mpf", "monitor"):        # BCP over localhost, as on a desktop
            self.assertEqual("service:godot", s[name]["network_mode"])
        self.assertEqual("service_completed_successfully", s["godot"]["depends_on"]["setup"]["condition"])
        for name in ("render-check", "test"):
            self.assertEqual(["headless"], s[name]["profiles"])
        for name in ("godot", "mpf", "monitor"):
            self.assertNotIn("profiles", s[name])
            self.assertIn("/tmp/.X11-unix:/tmp/.X11-unix", s[name]["volumes"])
            self.assertIn("..:/workspace", s[name]["volumes"])
        self.assertEqual("docker/Dockerfile", s["setup"]["build"]["dockerfile"])

    def test_overlays(self):
        self.assertIn("/dev/dri:/dev/dri", self.load("gpu.yml")["services"]["godot"]["devices"])
        self.assertEqual("unix:/run/tron/pulse.sock",
                         self.load("audio.yml")["services"]["godot"]["environment"]["PULSE_SERVER"])
        proc = self.load("proc.yml")["services"]
        self.assertIn("/dev/bus/usb:/dev/bus/usb", proc["mpf"]["devices"])
        self.assertEqual("1", proc["setup"]["build"]["args"]["WITH_PROC"])
        for name in ("godot", "mpf"):
            self.assertEqual("proc", proc[name]["environment"]["TRON_HW"])

    def test_dockerignore_lets_in_what_the_dockerfile_copies(self):
        with open(os.path.join(DOCKER, "Dockerfile"), encoding="utf-8") as f:
            copies = [line.split()[1:-1] for line in f if line.startswith("COPY")]
        with open(os.path.join(DOCKER, "Dockerfile.dockerignore"), encoding="utf-8") as f:
            allowed = {line.strip()[1:] for line in f if line.startswith("!")}
        for files in copies:
            for path in files:
                self.assertIn(path, allowed)
                self.assertTrue(os.path.exists(os.path.join(ROOT, path)), path)


class TestEntrypoint(unittest.TestCase):

    def setUp(self):
        self.ep = load_entrypoint()

    def test_godot_args(self):
        self.assertEqual([], self.ep.godot_args({}))
        env = {"GODOT_RENDERING_DRIVER": "opengl3", "DMD_SCREEN": "1", "DMD_FULLSCREEN": "1",
               "DMD_POSITION": "1920,0", "DMD_RESOLUTION": "1920x480", "GODOT_ARGS": "--always-on-top"}
        self.assertEqual(["--rendering-driver", "opengl3", "--screen", "1", "--position", "1920,0",
                          "--resolution", "1920x480", "--fullscreen", "--always-on-top"], self.ep.godot_args(env))

    def test_proc_dmd(self):
        self.assertEqual(["--", "--proc-dmd"], self.ep.godot_args({"TRON_HW": "proc"}))
        self.assertEqual(["--", "--x=1", "--proc-dmd"], self.ep.godot_args({"TRON_HW": "proc", "GODOT_ARGS": "-- --x=1"}))
        with self.assertRaises(SystemExit):
            self.ep.godot_args({"TRON_HW": "fast"})

    def test_godot_command(self):
        cmd = self.ep.godot_command({"DMD_SCREEN": "2"}, godot="/opt/godot/godot")
        self.assertEqual(["/opt/godot/godot", "--path", tc.GAME, "--screen", "2"], cmd)

    def test_mpf_command(self):
        self.assertEqual(["game", ".", "-c", "config,hw_virtual,free_play", "-t"], self.ep.mpf_command({})[-5:])
        self.assertEqual(["game", ".", "-c", "config,hw_virtual", "-t"], self.ep.mpf_command({"FREE_PLAY": "0"})[-5:])
        self.assertIn("config,hw_virtual,free_play", self.ep.mpf_command({"FREE_PLAY": ""}))     # compose's unset value
        self.assertEqual(["game", ".", "-c", "config,hw_proc"], self.ep.mpf_command({"TRON_HW": "proc",
                                                                                   "MPF_TEXT_UI": "1"})[-4:])
        self.assertEqual("monitor", self.ep.monitor_command()[-1])

    def test_display(self):
        self.assertEqual(":0.1", self.ep.display_env({"DISPLAY": ":0", "DMD_DISPLAY": ":0.1"}, "DMD_DISPLAY")["DISPLAY"])
        self.assertEqual(":0", self.ep.display_env({"DISPLAY": ":0", "DMD_DISPLAY": ""}, "DMD_DISPLAY")["DISPLAY"])
        with self.assertRaises(SystemExit):
            self.ep.check_display({})
        self.ep.check_display({"WAYLAND_DISPLAY": "wayland-0"})

    def test_workspace_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(5, len(self.ep.workspace_ready(tmp)))
            for mark in self.ep.workspace_ready(tmp):
                os.makedirs(os.path.join(tmp, mark))
            missing = self.ep.workspace_ready(tmp)           # all there, but media never stamped: setup again
            self.assertEqual(1, len(missing))
            self.assertIn("current media", missing[0])

    def test_unknown_role(self):
        with self.assertRaises(SystemExit):
            self.ep.main(["dance"], env={})


class TestMonitorUi(unittest.TestCase):

    def test_fetches_only_missing_files(self):
        with tempfile.TemporaryDirectory() as pkg:
            os.makedirs(os.path.join(pkg, "core", "ui"))
            with open(os.path.join(pkg, "core", "ui", "inspector.ui"), "w") as f:
                f.write("<ui/>")
            found = subprocess.CompletedProcess([], 0, stdout=pkg + "\n")
            with mock.patch.object(setup.subprocess, "run", return_value=found), \
                    mock.patch.object(setup, "download", return_value=b'<?xml version="1.0"?>\n<ui version="4.0"/>') as dl:
                self.assertEqual(3, setup.install_monitor_ui("python"))
            self.assertEqual(3, dl.call_count)
            for name in tc.MPF_MONITOR_UI_FILES:
                self.assertTrue(os.path.isfile(os.path.join(pkg, "core", "ui", name)))
            self.assertTrue(dl.call_args[0][0].startswith(tc.MPF_MONITOR_UI_URL))

    def test_rejects_non_ui(self):
        with tempfile.TemporaryDirectory() as pkg:
            found = subprocess.CompletedProcess([], 0, stdout=pkg)
            with mock.patch.object(setup.subprocess, "run", return_value=found), \
                    mock.patch.object(setup, "download", return_value=b"<html>404</html>"):
                with self.assertRaises(SystemExit):
                    setup.install_monitor_ui("python")


if __name__ == "__main__":
    unittest.main()
