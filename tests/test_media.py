"""Media bridge: ROM text formatting and the BCP triggers sent to the media controller."""
import unittest
from unittest import mock

from tests.tron_test import TronTestCase
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "game"))
from tron.media_bridge import format_rom_text   # noqa: E402


class TestRomText(unittest.TestCase):

    def test_printf(self):
        self.assertEqual("BALL 2", format_rom_text("BALL %d", [2]))
        self.assertEqual("1,234,560", format_rom_text("%,02lu", [1234560]))
        self.assertEqual("00", format_rom_text("%,02lu", [0]))      # score 0 as the ROM shows it
        self.assertEqual("000042", format_rom_text("%06d", [42]))
        self.assertEqual("PLAYER 3", format_rom_text("PLAYER %u", [3]))
        self.assertEqual("ZUSE", format_rom_text("%s", ["ZUSE"]))

    def test_plural_and_ordinal(self):
        self.assertEqual("1 BALL", format_rom_text("%d %P0/BALL/BALLS%", [1]))
        self.assertEqual("3 BALLS", format_rom_text("%d %P0/BALL/BALLS%", [3]))
        self.assertEqual("2ND", format_rom_text("%d%P1/ST/ND/RD/TH%", [2]))

    def test_no_name_where_a_number_goes(self):
        # a name or a tuple given for a number prints nothing (it printed "CASTOR" as combo points)
        self.assertEqual("", format_rom_text("%,02lu", ["CASTOR"]))
        self.assertEqual(" MORE TO", format_rom_text("%u MORE TO", [(0, 2)]))
        self.assertEqual("", format_rom_text("%s", [None]))


class TestBridge(TronTestCase):

    def test_deff_and_sound_triggers(self):
        bridge = self.tron.media
        if not bridge.data:
            self.skipTest("media data not generated (scripts/gen_media.py)")
        self.fill_trough()
        self.hit_and_release_switch("s_start_button")
        self.advance_time_and_run(2)
        with mock.patch.object(bridge, "connected", return_value=True), \
                mock.patch.object(self.machine.bcp, "interface") as iface:
            trig = iface.bcp_trigger
            self.tron.deff_start(25, hold=True, total=1500000)
            plays = [c.kwargs for c in trig.call_args_list if c.kwargs["name"] == "slides_play"
                     and "deff_025" in c.kwargs["settings"]
                     and c.kwargs["settings"]["deff_025"]["action"] == "play"]
            self.assertEqual("TOTAL BONUS", plays[-1]["line0"])
            self.assertEqual("1,500,000", plays[-1]["line1"])
            trig.reset_mock()
            self.tron.media.sound(0x01b)                  # main play music: looped on the music bus
            sent = trig.call_args_list[-1].kwargs["settings"]
            (key, settings), = sent.items()
            self.assertEqual("music", settings["bus"])
            self.assertEqual(-1, settings["loops"])
            self.tron.media.sound(0x001)                  # channel stop: stops the music
            self.assertEqual({"action": "stop", "key": key}, trig.call_args_list[-1].kwargs["settings"][key])

    def _slide_plays(self, iface, slide):
        return [c.kwargs for c in iface.bcp_trigger.call_args_list if c.kwargs["name"] == "slides_play"
                and slide in c.kwargs["settings"] and c.kwargs["settings"][slide]["action"] == "play"]

    def test_combo_text_through_the_switches(self):
        # "WAY / COMBO / CASTOR" on the DMD: deff 138's kwargs went to the ROM's printf lines in call order,
        # so the combo name took the points' place, the count took the jackpot's and the count was not drawn
        bridge = self.tron.media
        if not bridge.data:
            self.skipTest("media data not generated (scripts/gen_media.py)")
        self.fill_trough()
        self.hit_and_release_switch("s_start_button")
        self.advance_time_and_run(2)
        self.release_switch_and_run("s_shooter_lane", 1)
        with mock.patch.object(bridge, "connected", return_value=True), \
                mock.patch.object(self.machine.bcp, "interface") as iface:
            self.hit_and_release_switch("s_l_ramp_exit")         # left ramp: opens the combo window
            self.advance_time_and_run(0.3)
            self.hit_and_release_switch("s_left_orbit")          # left orbit: 2-way combo CASTOR
            self.advance_time_and_run(0.3)
            plays = self._slide_plays(iface, "deff_138")
        self.assertTrue(plays, "no 2-way combo display")
        kw = plays[-1]
        jackpot = self.tron.hook("eol_combo_jackpot_value")
        self.assertEqual(["%u", "WAY", "COMBO", "%,02lu", "%s", "JACKPOT=%,02lu"], bridge.data["deffs"][138]["text"])
        self.assertEqual("2", kw["line0"])                       # the count, in the ring font
        self.assertEqual(("WAY", "COMBO"), (kw["line1"], kw["line2"]))
        self.assertRegex(kw["line3"], r"^\d{1,3}(,\d{3})+$")    # the points
        self.assertEqual("CASTOR", kw["line4"])                  # the named combo, on its own row
        self.assertEqual("JACKPOT=" + format_rom_text("%,02lu", [jackpot]), kw["line5"])
        with mock.patch.object(bridge, "connected", return_value=True), \
                mock.patch.object(self.machine.bcp, "interface") as iface:
            self.tron.deff_start(138, points=300000, named=None, count=3, total=2, jackpot=850000)
            kw = self._slide_plays(iface, "deff_138")[-1]
        self.assertEqual(("3", "300,000", "", "JACKPOT=850,000"), (kw["line0"], kw["line3"], kw["line4"], kw["line5"]))

    def test_end_of_line_more_text(self):
        # deff 55 prints only `more`; before / after / flags pick the screen
        bridge = self.tron.media
        if not bridge.data:
            self.skipTest("media data not generated (scripts/gen_media.py)")
        lines = bridge.deff_lines(55, dict(before=(0, 2), after=(1, 2), flags=8, more=3, screen=2))
        self.assertEqual("3 MORE TO", lines["line4"])

    def test_sounds_go_to_the_gmc_client(self):
        # MPF's bcp_trigger() skips clients without a registered handler, and GMC registers none for
        # sounds_play: the bridge must address GMC (the "local_display" client) directly
        bridge = self.tron.media
        if not bridge.data:
            self.skipTest("media data not generated (scripts/gen_media.py)")
        client = mock.Mock()
        with mock.patch.object(bridge, "connected", return_value=True), \
                mock.patch.object(self.machine.bcp, "interface") as iface, \
                mock.patch.object(self.machine.bcp, "transport") as transport:
            transport.get_named_client.return_value = client
            bridge.sound(0x01b)
            iface.bcp_trigger.assert_not_called()
            kw = iface.bcp_trigger_client.call_args.kwargs
            self.assertIs(client, kw["client"])
            self.assertEqual("sounds_play", kw["name"])
            transport.get_named_client.assert_called_with("local_display")
        self.assertFalse(self.machine.bcp.transport.get_transports_for_handler("sounds_play"))   # why

    def test_score_display_args(self):
        bridge = self.tron.media
        if not bridge.data:
            self.skipTest("media data not generated (scripts/gen_media.py)")
        self.assertEqual("FREE PLAY", bridge.credits_text())           # unit tests run on free play
        self.tron.adj[34] = 0
        self.assertEqual("CREDITS 0", bridge.credits_text())
        self.tron.credit_model.counter = 0                              # one coin of USA 10's three
        self.assertEqual("CREDITS 1/3", bridge.credits_text())
        self.tron.credit_model.credits = 2
        self.assertEqual("CREDITS 2 1/3", bridge.credits_text())
        self.fill_trough()
        self.hit_and_release_switch("s_start_button")
        self.advance_time_and_run(2)
        args = bridge.deff_lines(19, {})
        self.assertEqual("BALL 1", args["line0"])
        self.assertEqual("REPLAY AT 20,000,000", args["replay"])      # auto replay, first level
        self.assertEqual((1, 1, "00", ""), (args["players"], args["player"], args["p1"], args["p2"]))
        self.machine.game.player.score += 5000
        bridge.score_changed()
        args = bridge.score_display_args()
        self.assertEqual(("5,000", 0), (args["award"], args["award_age"]))
        for key in ("bar_ds", "bar_bumpers", "bar_spinners", "bar_zfs", "bar_clu", "bar_gem"):
            self.assertEqual(0, args[key])

    def test_hurryup_bar_gone_when_ended_early(self):
        # clu_end_show_total zeroes the bar (FUN_01023010(0)): CLU made with 9 s left showed a 3-dot bar on the
        # panel's separator for the rest of the game (seen in Portal Multiball, Xavier NX full game 2026-10-12)
        bridge = self.tron.media
        if not bridge.data:
            self.skipTest("media data not generated (scripts/gen_media.py)")
        self.fill_trough()
        self.hit_and_release_switch("s_start_button")
        self.advance_time_and_run(2)
        clock = self.tron.features_by_name["clu"].clock
        clock.start()
        clock.seconds = 25
        self.assertEqual(10, bridge.score_display_args()["bar_clu"])
        clock.seconds = 9
        self.assertEqual(3, bridge.score_display_args()["bar_clu"])
        clock.kill()                                    # clu_end_now: all shots made, 9 s left
        self.assertEqual(9, clock.seconds)
        self.assertEqual(0, bridge.score_display_args()["bar_clu"])

    def test_missing_value_is_blank(self):
        bridge = self.tron.media
        if not bridge.data:
            self.skipTest("media data not generated (scripts/gen_media.py)")
        lines = {k: v for k, v in bridge.deff_lines(133, {}).items() if k.startswith("line")}
        self.assertEqual({"line0": "EXTRA", "line1": "BALL", "line2": ""}, lines)


class TestLiveDeffs(TronTestCase):

    def _bridge(self):
        bridge = self.tron.media
        if not bridge.data:
            self.skipTest("media data not generated (scripts/gen_media.py)")
        self.fill_trough()
        self.hit_and_release_switch("s_start_button")
        self.advance_time_and_run(2)
        return bridge

    @staticmethod
    def _lines(args):
        return {k: v for k, v in args.items() if k.startswith("line")}

    def test_panel_refresh_keeps_each_effects_lines(self):
        """Light Cycle total over the score display: the 0.25 s panel refresh sent deff 19's BALL n /
        score lines to deff 90 too (its slide showed BALL 1 over LIGHT CYCLE)."""
        bridge = self._bridge()
        self.assertEqual(19, self.tron.display.bg)
        with mock.patch.object(bridge, "connected", return_value=True), \
                mock.patch.object(self.machine.bcp, "interface") as iface:
            bridge.deff_start(90, 207, total=5650000)
            iface.bcp_trigger.reset_mock()
            bridge.score_changed()
            sent = {list(c.kwargs["settings"])[0]: c.kwargs for c in iface.bcp_trigger.call_args_list
                    if c.kwargs["name"] == "slides_play"}
        self.assertEqual("BALL 1", sent["deff_019"]["line0"])
        self.assertNotIn("line0", sent["deff_090"])
        self.assertEqual("00", sent["deff_090"]["p1"])

    def test_zuse_values(self):
        """deffs 95 / 96 print zfs_timer and zfs_value from RAM (they were blank)."""
        bridge = self._bridge()
        zuse = self.tron.features_by_name["zuse"]
        zuse.clock.seconds, zuse.value = 23, 15000
        self.assertEqual({"line0": "23", "line1": "ALL TARGETS=15,000"}, self._lines(bridge.deff_lines(95, {})))
        self.assertEqual({"line0": "15K", "line1": "23", "line2": "ALL TARGETS=15,000"},
                         self._lines(bridge.deff_lines(96, {"k": 15})))
        zuse.clock.seconds = 22                         # a refresh sends the new value
        with mock.patch.object(bridge, "connected", return_value=True), \
                mock.patch.object(self.machine.bcp, "interface") as iface:
            bridge.deff_start(95, 1)
            zuse.clock.seconds = 21
            bridge.score_changed()
            last = [c.kwargs for c in iface.bcp_trigger.call_args_list
                    if c.kwargs["name"] == "slides_play" and "deff_095" in c.kwargs["settings"]][-1]
        self.assertEqual("21", last["line0"])

    def test_sos_stage_text(self):
        """deff 114 shows SHOOT / the current stage's item (the capture's FLYNNS ARCADE on every stage)."""
        bridge = self._bridge()
        sos = self.tron.features_by_name["sea_of_simulation"]
        for stage, item in ((0, "FLYNNS ARCADE"), (2, "CLU HELMETS"), (8, "TRON TARGETS")):
            sos.stage = stage
            self.assertEqual({"line0": "SEA OF", "line1": "SIMULATION", "line2": "SHOOT", "line3": item},
                             self._lines(bridge.deff_lines(114, {})))
        self.assertEqual("200,000", bridge.deff_lines(117, {"value": 200000, "done": 0})["line0"])
        sos.skip_shown = (2, 3000000)                   # skipped CLU stage (it printed the stage number "02")
        self.assertEqual({"line0": "CLU", "line1": "BONUS", "line2": "3,000,000"},
                         self._lines(bridge.deff_lines(115, {})))

    def test_letter_args(self):
        """deffs 91 / 107 get the collected and new letters for tron/letter_panel.gd."""
        bridge = self._bridge()
        args = bridge.deff_lines(91, {"lit": 9, "new": 2})
        self.assertEqual((9, 2, "COLLECT"), (args["lit"], args["new"], args["line0"]))
        args = bridge.deff_lines(107, {"old": 1, "new": 4})
        self.assertEqual((1, 4), (args["old"], args["new"]))

    def test_letter_states_from_switch_hits(self):
        """The letters the ZUSE / TRON deffs draw come with the deff from the target switches: the letters
        collected before (solid) and the one just hit (blinks, then solid) [zuse_letter_hit 0x01033790,
        deff_091 0x01033b3c, deff_107 0x0102c870]. U then E: deff 91 with lit 0 / new U, then lit U / new E."""
        bridge = self._bridge()
        self.release_switch_and_run("s_shooter_lane", 1)
        self.hit_and_release_switch("s_left_bumper")           # playfield valid (no ZEN charge: it would
        self.advance_time_and_run(4)                           # complete TRON on the next new letter)
        with mock.patch.object(bridge, "connected", return_value=True), \
                mock.patch.object(self.machine.bcp, "interface") as iface:
            for sw in ("s_zuse_u", "s_zuse_e", "s_tron_t", "s_tron_o"):
                self.hit_and_release_switch(sw)
                self.advance_time_and_run(0.5)                # the second hit while the first deff runs
            plays = [(list(c.kwargs["settings"])[0], c.kwargs) for c in iface.bcp_trigger.call_args_list
                     if c.kwargs["name"] == "slides_play"
                     and list(c.kwargs["settings"].values())[0]["action"] == "play"]
        zuse = [(kw["lit"], kw["new"]) for slide, kw in plays if slide == "deff_091"]
        tron = [(kw["old"], kw["new"]) for slide, kw in plays if slide == "deff_107"]
        self.assertEqual([(0, 2), (2, 8)], zuse)              # bit 0 = Z: U = 2, E = 8
        self.assertEqual([(0, 1), (1, 4)], tron)              # T = 1, O = 4
        self.assertEqual(["lit", "new"], bridge.data["deffs"][91]["args"])
        self.assertEqual(["old", "new"], bridge.data["deffs"][107]["args"])
        self.assertEqual("letters", bridge.data["deffs"][91]["source"])

