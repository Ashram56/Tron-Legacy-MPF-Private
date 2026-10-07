"""PuP Pack: the trigger map covers the pack, the engine fires rows as PinUP Player does, and the game sends
them to Godot and mutes the ROM music only once Godot's PuP player is ready."""
import os
import sys
import unittest
from unittest import mock

from tests.tron_test import GAME, ROOT, TronTestCase

sys.path.insert(0, GAME)
from tron_pup import engine, pupfiles, settings   # noqa: E402

PACK = os.path.join(ROOT, "pup_pack", "trn_174h")
HAVE_PACK = os.path.exists(os.path.join(PACK, "triggers.pup"))


class TestPupFiles(unittest.TestCase):

    def test_expression(self):
        self.assertEqual([("D", 14, None)], pupfiles.parse_expression("D14"))
        self.assertEqual([("D", 0, 1)], pupfiles.parse_expression("D0=1"))
        self.assertEqual([("W", 11, 1), ("L", 35, 1)], pupfiles.parse_expression("W11=1,L35=1"))
        with self.assertRaises(ValueError):
            pupfiles.parse_expression("X5")

    def test_event_condition(self):
        self.assertEqual(("tron_deff_112", ("award", "1")), engine.parse_event("tron_deff_112{award==1}"))
        self.assertEqual(("tron_deff_25", None), engine.parse_event("tron_deff_25"))

    def test_settings_env_off(self):
        with mock.patch.dict(os.environ, {"TRON_PUP": "0"}):
            self.assertFalse(settings.load()["pup"]["enabled"])
        cfg = settings.load()
        self.assertIn("third_screen", cfg["pup"])


class TestSetup(unittest.TestCase):
    def test_native_video_on_windows_and_macos(self):
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
        import pup_setup
        with mock.patch.dict(os.environ, {"TRON_NATIVE_VIDEO": ""}):
            self.assertTrue(pup_setup.native_video("windows"))
            self.assertTrue(pup_setup.native_video("macos"))
            self.assertFalse(pup_setup.native_video("linux"))
        with mock.patch.dict(os.environ, {"TRON_NATIVE_VIDEO": "0"}):
            self.assertFalse(pup_setup.native_video("windows"))
        for name in ("native_video.gdextension", "native_video.windows.release.x86_64.dll",
                     "native_video.windows.debug.x86_64.dll", "libnative_video.macos.debug.dylib",
                     "libnative_video.macos.release.dylib"):
            self.assertTrue(os.path.exists(os.path.join(pup_setup.NATIVE_SRC, name)), name)

    def test_gozen_on_linux_only(self):
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
        import pup_setup
        self.assertTrue(pup_setup.gozen("linux", "arm64"))
        self.assertTrue(pup_setup.gozen("linux", "x86_64"))
        self.assertFalse(pup_setup.gozen("windows", "x86_64"))
        self.assertFalse(pup_setup.gozen("macos", "arm64"))
        with mock.patch.dict(os.environ, {"TRON_GOZEN": "0"}):
            self.assertFalse(pup_setup.gozen("linux", "arm64"))
        for name in ("gozen.gdextension", "video_playback.gd", "yuv_to_rgb_compatibility.gdshader",
                     "bin/libgozen.linux.template_release.arm64.so",
                     "bin/libgozen.linux.template_release.x86_64.so"):
            self.assertTrue(os.path.exists(os.path.join(pup_setup.GOZEN_SRC, name)), name)


@unittest.skipUnless(HAVE_PACK, "PuP Pack not checked out (git submodule update --init pup_pack)")
class TestEngine(unittest.TestCase):

    def setUp(self):
        self.sent, self.t = [], [0.0]
        self.engine = engine.build(PACK, self.sent.append, lambda: self.t[0])

    def ids(self):
        return [c["trigger"] for c in self.sent]

    def test_every_row_is_mapped(self):
        self.assertEqual([], [r.id for r in self.engine.unmapped])

    def test_drain(self):
        # D14 (BONUS): drain videos on both backglass layers, the default background back, music muted for the drain
        self.engine.on_event("tron_deff_25", total=1000)
        self.assertEqual([16, 17, 106, 134, 163, 164], self.ids())
        drain_bg2 = self.sent[1]
        self.assertEqual((12, "Drain", "StopPlayer"), (drain_bg2["screen"], drain_bg2["playlist"], drain_bg2["mode"]))

    def test_rest_seconds(self):
        self.engine.on_event("tron_deff_20")            # Ball Saved, RestSeconds 3
        self.t[0] = 2.0
        self.engine.on_event("tron_deff_20")
        self.t[0] = 3.5
        self.engine.on_event("tron_deff_20")
        self.assertEqual([12, 12], self.ids())

    def test_condition(self):
        self.engine.on_event("tron_deff_112", award=2)
        self.assertEqual([20], self.ids())                # SUPER POPS only
        self.engine.on_event("tron_deff_112", award=1)
        self.assertEqual([20, 19], self.ids())

    def test_same_command_once(self):
        # the 12 Disc Battle rows all play the DiscBattle playlist on the top layer: one command
        self.engine.on_event("tron_deff_111", left=3)
        self.assertEqual([31], self.ids())

    def test_game_start_and_mode(self):
        self.engine.on_event("player_added", num=1, player=None)
        self.assertEqual([7, 120, 159], self.ids())       # start video, main gameplay music (SetBG), topper logo
        self.assertEqual("SetBG", self.sent[1]["mode"])
        self.sent.clear()
        self.engine.on_event("tron_deff_76")              # gem intro
        self.assertEqual([79, 91, 115, 174], self.ids())
        self.sent.clear()
        self.engine.on_event("tron_deff_79", total=1)     # gem total: everything gem stops
        self.assertEqual({"StopFile"}, {c["mode"] for c in self.sent})

    def test_mapped_effects_exist(self):
        # an upstream renumbering of the display effects would leave PuP triggers on dead events
        import csv
        with open(os.path.join(ROOT, "assets", "mpf_package", "event_map.csv"), encoding="utf-8") as f:
            deffs = {int(row["deff"]) for row in csv.DictReader(f)}
        for name in self.engine.event_names:
            if name.startswith("tron_deff_"):
                self.assertIn(int(name[len("tron_deff_"):]), deffs, name)

    def test_switches(self):
        self.engine.on_switch("s_tron_t")
        self.engine.on_switch("s_shooter_lane")
        self.assertEqual([150, 231], self.ids())


class TestPupMachine(TronTestCase):

    def setUp(self):
        super().setUp()
        self.pup = self.machine.modes["pup"]
        if self.pup.engine is None:
            self.skipTest("PuP Pack not checked out or PuP disabled")

    def test_triggers_reach_godot_after_ready(self):
        client = mock.Mock()
        with mock.patch.object(self.machine.bcp, "interface") as iface, \
                mock.patch.object(self.machine.bcp, "transport") as transport:
            transport.get_named_client.return_value = client
            self.machine.events.post("tron_deff_20")
            self.advance_time_and_run(1)
            self.assertFalse([c for c in iface.bcp_trigger_client.call_args_list
                              if c.kwargs["name"] == "pup_play"])          # Godot not ready: nothing sent
            self.machine.events.post("pup_ready")
            self.advance_time_and_run(1)
            self.fill_trough()
            self.hit_and_release_switch("s_start_button")                 # the real game start: D2
            self.advance_time_and_run(2)
            self.assertIn(7, [c.kwargs.get("trigger") for c in iface.bcp_trigger_client.call_args_list])
            self.machine.events.post("tron_deff_20")
            self.advance_time_and_run(1)
            plays = [c.kwargs for c in iface.bcp_trigger_client.call_args_list if c.kwargs["name"] == "pup_play"]
            self.assertIn(2, [p["trigger"] for p in plays])                  # pup_boot: D0=1 rows
            self.assertEqual("BallSaved", plays[-1]["playlist"])
            self.assertIs(client, plays[-1]["client"])

    def test_rom_music_muted_when_pup_ready(self):
        bridge = self.tron.media
        if not bridge.data:
            self.skipTest("media data not generated (scripts/gen_media.py)")
        with mock.patch.object(bridge, "connected", return_value=True), \
                mock.patch.object(self.machine.bcp, "interface") as iface, \
                mock.patch.object(self.machine.bcp, "transport"):
            bridge.sound(0x01b)                                  # before PuP: the ROM music plays
            self.assertEqual("sounds_play", iface.bcp_trigger_client.call_args.kwargs["name"])
            self.machine.events.post("pup_ready")
            self.advance_time_and_run(0.1)
            stops = [c.kwargs for c in iface.bcp_trigger_client.call_args_list
                     if c.kwargs["name"] == "sounds_play"][-1]  # the running ROM music is stopped
            (key, settings_), = stops["settings"].items()
            self.assertEqual("stop", settings_["action"])
            iface.reset_mock()
            bridge.sound(0x01b)                                  # music call: dropped
            bridge.sound(0x045)                                  # a sound effect still plays
            calls = [c.kwargs for c in iface.bcp_trigger_client.call_args_list if c.kwargs["name"] == "sounds_play"]
            self.assertEqual(1, len(calls))
            self.assertNotEqual("music", list(calls[0]["settings"].values())[0]["bus"])

    def test_attract_cycle(self):
        with mock.patch.object(self.pup.engine, "on_event") as on_event:
            self.advance_time_and_run(float(self.pup.pup.get("attract_cycle_seconds", 60)) + 1)
            self.assertIn("pup_attract_cycle", [c.args[0] for c in on_event.call_args_list])
