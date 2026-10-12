"""The Visual Pinball X overlay (config.yaml + hw_vpx.yaml + tron/vpx_hardware.py) answers the table's controller
calls as VPinMAME does, and scripts/vpx_table.py rewrites the table script's loader. The calls go to the platform
the way MPF's "vpcom_bridge" BCP handler sends them (scripts/vpx_bridge.py --check drives a live game the same way)."""
import asyncio
import os
import sys
import time

from mpf.tests.MpfBcpTestCase import MpfBcpTestCase

from tests.tron_test import ROOT, TronTestCase

sys.path.insert(0, os.path.join(ROOT, "scripts"))
import vpx_bridge  # noqa: E402
import vpx_table  # noqa: E402

TROUGH = (18, 19, 20, 21)


class TestVpx(TronTestCase, MpfBcpTestCase):

    def get_config_file(self):
        return "../../tests/machine_vpx.yaml"     # relative to game/config

    def get_platform(self):
        return False                              # the overlay's own platform

    def _initialize_machine(self):
        """MPF waits in init_phase_5 until the table connects: connect as the bridge's Run() does."""
        init = asyncio.ensure_future(self.machine.initialize())
        end = time.time() + 60
        while not init.done() and not self._exception:
            self.loop.run_once()
            platform = getattr(self.machine, "hardware_platforms", {}).get("virtual_pinball")
            if platform is not None and not platform._started.is_set():
                self.assertTrue(platform.vpx_start())
            self.assertLess(time.time(), end, "MPF did not start")
        init.result()
        self.machine.events.process_event_queue()
        self.advance_time_and_run(.001)

    def vpx(self, subcommand, **kwargs):
        return getattr(self.machine.hardware_platforms["virtual_pinball"], "vpx_" + subcommand)(**kwargs)

    def set_switch(self, number, value, run=0.05):
        self.assertTrue(self.vpx("set_switch", number=number, value=value))
        self.advance_time_and_run(run)

    def solenoids(self):
        return dict(self.vpx("changed_solenoids"))

    def test_numbers_match_pinmame(self):
        sw = self.machine.switches
        for name, number in (("s_left_flipper", "84"), ("s_right_flipper", "82"), ("s_plumb_bob_tilt", "-7"),
                             ("s_slam_tilt", "-6"), ("s_coin", "65"), ("s_start_button", "16"),
                             ("s_service_back", "-3"), ("s_service_select", "0"), ("s_trough_1_r", "21"),
                             ("s_disc_opto", "41"), ("s_coin_door_open", "-4")):
            self.assertEqual(number, sw[name].hw_switch.number, name)
        self.assertEqual("1", self.machine.coils["c_trough_up_kicker"].hw_driver.number)
        self.assertEqual("17", self.machine.coils["f_zen_flasher"].hw_driver.number)
        self.assertEqual("65", self.machine.lights["l_start_button"].hw_drivers["white"][0].hw_number)
        tube = self.machine.lights["l_left_ramp_tube"].hw_drivers
        self.assertEqual(["101", "102", "103"], [tube[c][0].hw_number for c in ("blue", "green", "red")])

    def test_game_through_the_bridge(self):
        for number in TROUGH:                       # bsTrough.Balls = 4
            self.set_switch(number, True)
        self.advance_time_and_run(2)
        self.assertEqual(4, self.machine.ball_devices["bd_trough"].balls)
        self.assertNotIn(33, self.solenoids())      # flippers off in attract

        self.set_switch(16, -1)                     # START (VBScript True is -1)
        self.set_switch(16, 0, run=3)
        self.assertModeRunning("game")
        sols = self.solenoids()
        self.assertEqual(255, sols.get(1), sols)    # trough up-kicker: reported though the pulse is over
        self.assertEqual(255, sols.get(33))         # flippers enabled: the table's fast flips take over
        self.assertEqual(0, self.solenoids().get(1))    # then off at the next poll
        self.assertNotIn(1, self.solenoids())           # and nothing more until it fires again

        self.set_switch(84, True)                   # left flipper button: coils 15 and 12 follow it
        self.assertTrue({15: 255, 12: 255}.items() <= self.solenoids().items())
        self.set_switch(84, False)
        self.assertTrue({15: 0, 12: 0}.items() <= self.solenoids().items())

        lamps = dict(self.vpx("changed_lamps"))
        self.assertTrue(lamps)
        self.assertTrue(set(lamps.values()) <= {0, 1}, lamps)
        self.assertTrue(self.vpx("set_switch", number=66, value=True))      # coin 2: not wired, no error
        self.assertFalse(self.vpx("get_switch", number=66))
        self.assertTrue(self.vpx("get_switch", number=18))

    def test_coin_door_cuts_the_coils(self):
        for number in TROUGH:
            self.set_switch(number, True)
        self.advance_time_and_run(2)
        self.set_switch(16, True)
        self.set_switch(16, False, run=3)
        self.assertModeRunning("game")
        self.assertEqual(255, self.solenoids().get(33))
        self.set_switch(-4, True)                   # End: the door opens (the table script toggles -4)
        self.assertTrue(self.vpx("get_switch", number=-4))
        self.assertEqual(4, self.machine.tron.display.fg)              # "50V / 20V DISABLED"
        self.assertEqual(0, self.solenoids().get(33))                  # fast flips off: no flipper power
        self.machine.coils["c_left_slingshot"].pulse()
        self.set_switch(84, True)
        self.assertEqual({}, {n: v for n, v in self.solenoids().items() if v})   # nothing drives
        self.set_switch(84, False)
        self.set_switch(-4, False)                  # closed: power back, the flippers with it
        self.assertEqual(255, self.solenoids().get(33))
        self.assertNotEqual(4, self.machine.tron.display.fg)

    def test_ramp_tubes_are_rgb_lamps(self):
        self.machine.lights["l_left_ramp_tube"].color([255, 0, 128])
        self.advance_time_and_run(.1)
        lamps = dict(self.vpx("changed_lamps"))
        self.assertEqual(0, lamps.get(102, 0))
        self.assertEqual(255, lamps[103])           # red
        self.assertIn(lamps[101], (128, 129))       # blue

    def test_pulse_switch_and_stop(self):
        self.assertTrue(self.vpx("pulsesw", number=-7))
        self.assertTrue(self.vpx("stop"))           # the table closed (no quit: the bridge did not start MPF)


class TestVpxPro(TestVpx):
    """hw_vpx_pro.yaml: the Pro's numbers on the table (assets/docs/PRO_VS_LE.md), ramp tubes off."""

    def get_config_file(self):
        return "../../tests/machine_vpx_pro.yaml"

    def test_numbers_match_pinmame(self):
        self.assertEqual("pro", self.machine.variables.get_machine_var("machine_variant"))
        self.assertEqual("4", self.machine.switches["s_tron_t"].hw_switch.number)        # standups, reversed
        self.assertEqual("3", self.machine.coils["c_disc_direction_relay"].hw_driver.number)
        self.assertEqual("1-matrix", self.machine.lights["l_start_button"].hw_drivers["white"][0].number)

    def test_ramp_tubes_are_rgb_lamps(self):
        self.machine.lights["l_left_ramp_tube"].color([255, 0, 128])
        self.advance_time_and_run(.1)
        lamps = dict(self.vpx("changed_lamps"))
        self.assertEqual([0, 0, 0], [lamps.get(n, 0) for n in (101, 102, 103)])     # fiber_optics 0


class TestTableScript(TronTestCase):

    SCRIPT = ('Option Explicit\r\nConst UseVPMModSol = True\r\nLoadVPM "01560000", "sam.VBS", 3.10\r\n'
              'Const cGameName = "trn_174h"\r\nSub Table_Init\r\n\t.Run GetPlayerHWnd\r\nEnd Sub\r\n'
              'Sub Table_KeyDown(ByVal keycode)\r\n\tIf vpmKeyDown(keycode) Then Exit Sub\r\nEnd Sub\r\n')

    def test_loader_swapped(self):
        out = vpx_table.patch_script(self.SCRIPT)
        self.assertNotIn('\r\nLoadVPM', out)
        self.assertIn('LoadMPF "sam.VBS"\r\n', out)
        self.assertIn('CreateObject("TronMPF.Controller")', out)
        self.assertIn("Was: LoadVPM \"01560000\", \"sam.VBS\", 3.10", out)
        self.assertNotIn("\n\n", out.replace("\r\n", "\r"))          # line ends stay CRLF
        self.assertIn('Const cGameName = "trn_174h"\r\nSub Table_Init\r\n\t.Run GetPlayerHWnd\r\nEnd Sub\r\n', out)
        # End toggles the coin door (switch -4) before core.vbs sees the key
        self.assertIn('Sub Table_KeyDown(ByVal keycode)\r\n\tIf keycode = 207 Then Controller.Switch(-4) = '
                      'Not Controller.Switch(-4) : Exit Sub', out)
        self.assertTrue(out.endswith('\r\n\tIf vpmKeyDown(keycode) Then Exit Sub\r\nEnd Sub\r\n'))
        with self.assertRaises(ValueError):                        # twice is refused
            vpx_table.patch_script(out)
        with self.assertRaises(ValueError):
            vpx_table.patch_script("LoadVPM \"01560000\", \"WPC.VBS\", 3.10\n")

    def test_bridge_changes_are_vpinmame_arrays(self):
        self.assertIsNone(vpx_bridge.changes([]))                   # Empty: nothing changed
        self.assertEqual([[15, 255], [33, 0]], vpx_bridge.changes([["15", 255], [33, 0]]))
