"""The P-ROC machine config (config.yaml + the hw_proc.yaml overlay): MPF boots it against a mocked pinproc module whose decode()
is libpinproc's own SAM decoding, every switch, coil and light lands on a unique, valid P-ROC address that
matches the SAM tables, and the flippers, slings, pops, DMD and ramp tubes reach the P-ROC as expected."""
import csv
import os
import re
from unittest.mock import MagicMock

from mpf.platforms import p_roc, p_roc_common
from ruamel.yaml import YAML

from tests.tron_test import ROOT, TronTestCase

MACHINE_TYPE_STERN_SAM = 6
PACKAGE = os.path.join(ROOT, "assets", "mpf_package", "config")
PROC_CONFIG = "../../tests/machine_proc_le.yaml"    # relative to game/config: config.yaml, then hw_proc_le.yaml (LE)
PRO_CONFIG = "../../tests/machine_proc.yaml"       # config.yaml, then hw_proc.yaml (Pro, the default)


def _atoi(text):
    m = re.match(r"\s*([+-]?\d+)", text)
    return int(m.group(1)) if m else 0


def _cdiv(a, b):        # C integer division and remainder (truncate toward zero), as in the C source
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b > 0) else -q


def _cmod(a, b):
    return a - b * _cdiv(a, b)


def sam_decode(text):
    """PRDecode(kPRMachineSternSAM, str), ported line for line from libpinproc src/pinproc.cpp
    (github.com/preble/libpinproc, commit 286c566, lines 355-366, 465-493 and 520). The result is uint16_t."""
    if text is None:
        return 0
    if len(text) == 3:
        x = (ord(text[1]) - 48) * 10 + (ord(text[2]) - 48)
    elif len(text) == 4:
        x = (ord(text[2]) - 48) * 10 + (ord(text[3]) - 48)
    else:
        return _atoi(text) & 0xffff
    first = text[0]
    if first in "Ll":
        value = 80 + 16 * (7 - _cmod(x - 1, 8)) + _cdiv(x - 1, 8)
    elif first in "Cc":
        value = x + 31
    elif first in "Ss":
        if text[1] in "Dd":
            value = (ord(text[2]) - 48) + 7 if len(text) == 3 else x + 7
        elif _cmod(x - 1, 16) < 8:
            value = 32 + 8 * _cdiv(x - 1, 8) + (7 - _cmod(x - 1, 8))
        else:
            value = 32 + (x - 1)
    else:
        value = _atoi(text)
    return value & 0xffff


# What libpinproc sets up for MachineTypeSternSAM (src/PRDevice.cpp, DriverLoadMachineTypeDefaults): driver
# groups 4-7 (drivers 32-63) are the SAM coil banks, groups 10-25 (drivers 80-207) the 10x8 lamp matrix, every
# Stern group active high (mappedSternDriverGroupPolarity). P-ROC switches 8-31 are SD1-SD24, 32 up the matrix.
COIL_DRIVERS = range(32, 64)
LAMP_DRIVERS = range(80, 208)
DEDICATED_SWITCHES = range(8, 32)
MATRIX_SWITCHES = range(32, 96)


class SamPinProcModule(MagicMock):
    """pinproc as MPF's own P-ROC test mocks it (mpf/tests/test_P_Roc.py), with libpinproc's SAM decode()."""
    DriverCount = 256
    EventTypeDMDFrameDisplayed = 5
    EventTypeSwitchClosedDebounced = 1
    EventTypeSwitchClosedNondebounced = 3
    EventTypeSwitchOpenDebounced = 2
    EventTypeSwitchOpenNondebounced = 4
    MachineTypePDB = 7
    MachineTypeSternSAM = MACHINE_TYPE_STERN_SAM
    SwitchCount = 255

    def aux_command_jump(self, number):
        return "jump{}".format(number)

    def aux_command_disable(self):
        return "disable"

    def aux_command_output_primary(self, data, extra_data, delay_time):     # sternSAM: enables 6, mux 1
        return ("out", data, extra_data, 6, True, delay_time)

    def aux_command_output_secondary(self, data, extra_data, delay_time):   # sternSAM: enables 11, mux 1
        return ("out", data, extra_data, 11, True, delay_time)

    def aux_command_delay(self, delay):
        return ("delay", delay)

    def decode(self, machine_type, device_str):
        assert machine_type == MACHINE_TYPE_STERN_SAM, machine_type
        return sam_decode(device_str)


class ProcCase(TronTestCase):
    """The machine on config.yaml + hw_proc.yaml with a mocked P-ROC."""
    RAMP_TUBES = False

    def get_config_file(self):
        return PROC_CONFIG

    def get_platform(self):
        return False

    def _mock_loop(self):
        super()._mock_loop()
        self.loop._wait_for_external_executor = True

    @staticmethod
    def _normalize(name):
        # pypinproc's PyObjToMachineType: strcmp(name, "sternSAM"), so the case must survive MPF's validation
        return MACHINE_TYPE_STERN_SAM if name == "sternSAM" else 0

    @staticmethod
    def _driver_get_state(driver_num):
        return {"driverNum": driver_num, "outputDriveTime": 0, "polarity": True, "state": False,
                "waitForFirstTimeSlot": False, "timeslots": 0, "patterOnTime": 0, "patterOffTime": 0,
                "patterEnable": False, "futureEnable": False}

    @staticmethod
    def _state(driver, **values):
        driver = dict(driver)
        driver.update(values)
        return driver

    def setUp(self):
        self._saved = (p_roc_common.PINPROC_IMPORTED, getattr(p_roc_common, "pinproc", None),
                       getattr(p_roc, "pinproc", None))
        module = SamPinProcModule()
        module.normalize_machine_type = self._normalize
        module.driver_state_pulse = lambda d, ms: self._state(d, state=1, outputDriveTime=ms, patterEnable=False)
        module.driver_state_disable = lambda d: self._state(d, state=0, outputDriveTime=0, patterEnable=False)
        module.driver_state_patter = lambda d, on, off, first, now: self._state(
            d, state=True, outputDriveTime=first, patterOnTime=on, patterOffTime=off, patterEnable=True)
        module.driver_state_pulsed_patter = None
        self.pinproc = MagicMock()
        self.pinproc.read_data = lambda module_, address: {0x01: 0x0002000e, 0x03: 0}.get(address, 0)
        self.pinproc.driver_get_state = self._driver_get_state
        self.pinproc.get_events = MagicMock(return_value=[])
        self.pinproc.switch_get_states = MagicMock(return_value=[2] * 256)     # every switch open
        module.PinPROC = MagicMock(return_value=self.pinproc)
        p_roc_common.PINPROC_IMPORTED = True
        p_roc_common.pinproc = p_roc.pinproc = module
        self.machine_config_patches["p_roc"] = {"use_separate_thread": False}
        self.machine_config_patches["machine_vars"] = {"proc_ramp_tubes": {
            "initial_value": str(int(self.RAMP_TUBES)), "value_type": "int", "persist": False}}
        super().setUp()

    def tearDown(self):
        super().tearDown()
        p_roc_common.PINPROC_IMPORTED, p_roc_common.pinproc, p_roc.pinproc = self._saved

    def sync(self):
        self.machine_run()
        self.machine.default_platform.run_proc_cmd_sync("_sync", 1)


def _load(path):
    with open(path, encoding="utf-8") as f:
        return YAML(typ="safe").load(f)


def _coil_table():
    """assets/io/coils.csv: SAM coil number -> MPF-style name (c_/f_ dropped)."""
    with open(os.path.join(ROOT, "assets", "io", "coils.csv"), encoding="utf-8") as f:
        return {int(row["coil"]): re.sub(r"[^a-z0-9]+", "_", row["name"].lower().replace("flash:", "")).strip("_")
                for row in csv.DictReader(f)}


class TestProcAddresses(ProcCase):

    def test_platform(self):
        platform = self.machine.default_platform
        self.assertEqual("<Platform.P-ROC>", repr(platform))
        self.assertEqual(MACHINE_TYPE_STERN_SAM, platform.machine_type)

    def test_every_switch(self):
        package = _load(os.path.join(PACKAGE, "switches.yaml"))["switches"]
        seen = {}
        for switch in self.machine.switches.values():
            number = switch.config["number"]
            self.assertIs(self.machine.default_platform, switch.platform, switch.name)
            proc = switch.hw_switch.number
            self.assertEqual(sam_decode(number), proc, switch.name)
            self.assertNotIn(proc, seen, "{} and {} share P-ROC switch {}".format(switch.name, seen.get(proc), proc))
            seen[proc] = switch.name
            if number.startswith("SD"):
                self.assertIn(proc, DEDICATED_SWITCHES, switch.name)
            else:
                self.assertRegex(number, r"^S\d\d$")
                self.assertIn(proc, MATRIX_SWITCHES, switch.name)
                self.assertEqual(package[switch.name]["number"], int(number[1:]), switch.name)
        self.assertEqual(len(package) + 13, len(seen))       # 46 matrix + 13 dedicated (hardware*.yaml)

    def test_every_coil(self):
        table = _coil_table()
        seen = {}
        virtual = []
        for coil in self.machine.coils.values():
            number = str(coil.config["number"])
            sam = int(number.lstrip("C"))
            self.assertEqual(table[sam], coil.name[2:], "{} is SAM coil {} {}".format(coil.name, sam, table[sam]))
            if coil.platform is not self.machine.default_platform:
                virtual.append(coil.name)
                continue
            proc = coil.hw_driver.number
            self.assertRegex(number, r"^C\d\d$")
            self.assertEqual(sam_decode(number), proc)
            self.assertIn(proc, COIL_DRIVERS, coil.name)
            self.assertNotIn(proc, seen, coil.name)
            seen[proc] = coil.name
            self.assertTrue(coil.hw_driver.polarity, coil.name)
        self.assertEqual(["c_aux_1_ticket_advance", "c_aux_2_ticket_meter", "c_aux_3_ticket_enable"], sorted(virtual))
        self.assertEqual(32, len(seen))

    def test_every_light(self):
        package = _load(os.path.join(PACKAGE, "lights.yaml"))["lights"]
        seen = {}
        for light in self.machine.lights.values():
            number = str(light.config["number"])
            if light.name in ("l_left_ramp_tube", "l_right_ramp_tube"):
                self.assertEqual(["blue", "green", "red"], sorted(light.hw_drivers))
                self.assertEqual("VirtualLight", type(light.hw_drivers["red"][0]).__name__)    # aux bus
                continue
            self.assertEqual(["white"], list(light.hw_drivers), light.name)
            proc = light.hw_drivers["white"][0].number
            self.assertRegex(number, r"^L\d\d$")
            self.assertEqual(package[light.name]["number"], int(number[1:]), light.name)
            self.assertEqual(sam_decode(number), proc)
            self.assertIn(proc, LAMP_DRIVERS, light.name)
            self.assertNotIn(proc, seen, light.name)
            seen[proc] = light.name
        self.assertEqual(len(package) - 2, len(seen))

    def test_known_addresses(self):
        """Spot checks against the SAM tables, worked out by hand from libpinproc's formulas."""
        switches = {"s_trough_4_l": 54, "s_trough_3": 53, "s_trough_2": 52, "s_trough_1_r": 51,   # S18-S21
                    "s_video_game_eject": 42, "s_start_button": 47, "s_disc_opto": 72,          # S11 S16 S41
                    "s_left_flipper": 16, "s_left_flipper_eos": 17, "s_right_flipper": 18,      # SD9-SD12
                    "s_right_flipper_eos": 19, "s_plumb_bob_tilt": 24, "s_slam_tilt": 25,       # SD17 SD18
                    "s_coin": 10, "s_service_back": 28, "s_service_select": 31}                 # SD3 SD21 SD24
        for name, proc in switches.items():
            self.assertEqual(proc, self.machine.switches[name].hw_switch.number, name)
        coils = {"c_trough_up_kicker": 32, "c_video_game_eject": 35, "c_shaker_motor_optional": 39,
                 "c_upper_left_flipper": 43, "c_left_flipper": 46, "c_right_flipper": 47,
                 "f_zen_flasher": 48, "c_disc_motor_relay": 61, "f_blue_disc": 63}
        for name, proc in coils.items():
            self.assertEqual(proc, self.machine.coils[name].hw_driver.number, name)
        lamps = {"l_tron_n": 192, "l_shoot_again": 179, "l_start_button": 200, "l_tournament_start_button": 184,
                 "l_l_inner_loop_arrow": 87}                                       # L01 L26 L65 L66 L64
        for name, proc in lamps.items():
            self.assertEqual(proc, self.machine.lights[name].hw_drivers["white"][0].number, name)
        self.assertTrue(self.machine.switches["s_disc_opto"].invert)          # optos stay NC

    def test_coils_reach_the_proc(self):
        self.machine.coils["c_trough_up_kicker"].pulse()
        self.sync()
        self.pinproc.driver_pulse.assert_called_with(32, 64)                     # ROM: 64 ms
        self.machine.coils["c_shaker_motor_optional"].enable()
        self.sync()
        self.pinproc.driver_schedule.assert_called_with(39, 0xffffffff, 0, True)
        self.machine.coils["c_orbit_up_down_post"].enable()
        self.sync()
        self.pinproc.driver_patter.assert_called_with(38, 1, 6, 64, True)        # ROM: 64 ms, then 1 ms on / 6 ms off
        self.advance_time_and_run(4.1)
        self.pinproc.driver_disable.assert_any_call(38)                          # max_hold_duration
        self.machine.coils["f_backpanel"].pulse(300)                             # > 255 ms: timed enable
        self.sync()
        self.pinproc.driver_schedule.assert_called_with(59, 0xffffffff, 0, True)
        self.machine.lights["l_shoot_again"].on()
        self.advance_time_and_run(.1)
        self.sync()
        self.pinproc.driver_schedule.assert_any_call(179, 0xffffffff, 0, True)     # (attract lamps reach the P-ROC too)

    def _rules(self, switch):
        """Driver states the P-ROC gets for a switch's closed/open events (latest rule per event)."""
        rules = {}
        for call in self.pinproc.switch_update_rule.call_args_list:
            num, event, _, drivers = call.args[:4]
            if num == switch:
                rules[event] = drivers
        return rules

    def test_flippers_and_autofires(self):
        self.fill_trough()
        self.hit_and_release_switch("s_start_button")
        self.advance_time_and_run(2)
        self.assertModeRunning("game")
        self.sync()
        left = self._rules(16)          # SD9: left flipper and upper left flipper
        closed = sorted((d["driverNum"], d["patterOnTime"], d["patterOffTime"], d["outputDriveTime"])
                        for d in left["closed_nondebounced"])
        self.assertEqual([(43, 1, 11, 40), (46, 1, 11, 40)], closed)    # 40 ms, then 1 ms on / 11 ms off
        self.assertEqual([43, 46], sorted(d["driverNum"] for d in left["open_nondebounced"]))
        self.assertEqual([(47, 1, 11, 40)], [(d["driverNum"], d["patterOnTime"], d["patterOffTime"],
                                               d["outputDriveTime"]) for d in self._rules(18)["closed_nondebounced"]])
        for switch, driver, ms in ((57, 44, 32), (58, 45, 32), (61, 40, 32), (62, 41, 32), (63, 42, 32)):
            drivers = self._rules(switch)["closed_nondebounced"]          # S26 S27 S30 S31 S32
            self.assertEqual([(driver, ms)], [(d["driverNum"], d["outputDriveTime"]) for d in drivers])
        self.machine.events.post("tron_tilt")
        self.advance_time_and_run(.1)
        self.sync()
        self.assertEqual([], self._rules(57).get("closed_nondebounced", []))     # tilt: slings off

    def test_dmd(self):
        frame = bytes(range(16)) * 256
        self.machine.dmds["dmd"].update(frame)
        self.sync()
        p_roc_common.pinproc.DMDBuffer.assert_called_with(128, 32)
        p_roc_common.pinproc.DMDBuffer.return_value.set_data.assert_called_with(frame)
        self.pinproc.dmd_draw.assert_called_with(p_roc_common.pinproc.DMDBuffer.return_value)

    def test_ramp_tubes_off_by_default(self):
        for call in self.pinproc.aux_send_commands.call_args_list:
            self.assertFalse([c for c in call.args[1] if isinstance(c, tuple)])


class TestProcRampTubes(ProcCase):
    RAMP_TUBES = True

    def _program(self):
        commands = self.pinproc.aux_send_commands.call_args_list[-2].args[1]   # [-1] is the jump that starts it
        self.assertEqual("disable", commands[0])
        return commands[1:]

    def test_tube_program(self):
        self.advance_time_and_run(.1)
        self.sync()
        self.assertEqual([("out", 0, 0, 6, True, 0), ("out", 0xee, 0, 11, True, 0),
                          ("out", 0xfe, 0, 11, True, 0), ("out", 0, 0, 6, True, 0),
                          ("out", 0xde, 0, 11, True, 0), ("out", 0xfe, 0, 11, True, 0),
                          ("delay", 250)], self._program()[:7])
        self.machine.lights["l_left_ramp_tube"].color("ff4400")      # orange 15/4/0
        self.machine.lights["l_right_ramp_tube"].color("0000ff")
        self.advance_time_and_run(.1)
        self.sync()
        program = self._program()
        self.assertEqual(28, len(program))
        left = [c[1] for c in program if c[0] == "out" and c[3] == 6][0::2]
        right = [c[1] for c in program if c[0] == "out" and c[3] == 6][1::2]
        self.assertEqual([0x20, 0x20, 0x30, 0x20], left)        # R every plane, G (4 = 0b0100) on plane 2
        self.assertEqual([0x08] * 4, right)
        self.assertEqual([250, 500, 1000, 2000], [c[1] for c in program if c[0] == "delay"])


class TestProcConfigVirtual(TronTestCase):
    """config.yaml + hw_proc.yaml with every device on the smart virtual platform: the whole config validates, and the
    flippers follow the game (ball start, tilt, next ball, game over)."""

    def get_config_file(self):
        return PROC_CONFIG

    def test_flippers_follow_the_game(self):
        flippers = self.machine.flippers
        self.assertEqual(["left_flipper", "right_flipper", "upper_left_flipper"], sorted(f.name for f in flippers.values()))
        self.assertEqual(5, len(self.machine.autofire_coils))
        self.fill_trough()
        self.hit_and_release_switch("s_start_button")
        self.advance_time_and_run(2)
        self.assertTrue(all(f._enabled for f in flippers.values()))
        self.assertTrue(all(a._enabled for a in self.machine.autofire_coils.values()))
        self.tron.adj[32] = 0                                    # no tilt warnings
        self.hit_and_release_switch("s_plumb_bob_tilt")
        self.advance_time_and_run(.1)
        self.assertTrue(self.tron.tilted)
        self.assertFalse(any(f._enabled for f in flippers.values()))
        self.assertFalse(any(a._enabled for a in self.machine.autofire_coils.values()))


def _pro_map():
    """assets/io/pro_vs_le_io_map.csv: {(kind, LE number): Pro number or None}."""
    out = {}
    with open(os.path.join(ROOT, "assets", "io", "pro_vs_le_io_map.csv"), encoding="utf-8") as f:
        for row in csv.DictReader(f):
            on_pro = row["le_name_on_pro_at"].strip()
            out[(row["kind"], int(row["number"]))] = int(on_pro) if on_pro.isdigit() else None
    return out


class TestProcPro(ProcCase):
    """hw_proc.yaml, the default: the Pro's IO assignments (assets/docs/PRO_VS_LE.md) on the P-ROC."""
    RAMP_TUBES = True

    def get_config_file(self):
        return PRO_CONFIG

    def proc(self, device):
        if hasattr(device, "hw_switch"):
            return device.hw_switch.number
        if hasattr(device, "hw_driver"):
            return device.hw_driver.number
        return device.hw_drivers["white"][0].number

    def test_machine_vars(self):
        self.assertEqual("pro", self.machine.variables.get_machine_var("machine_variant"))
        self.assertEqual(0, self.machine.variables.get_machine_var("fiber_optics"))

    def test_pro_numbers(self):
        on = self.machine.default_platform
        for name, number in (("s_tron_t", "S04"), ("s_tron_r", "S03"), ("s_tron_o", "S02"), ("s_tron_n", "S01")):
            self.assertEqual(sam_decode(number), self.proc(self.machine.switches[name]), name)
        for name, number in (("c_disc_direction_relay", "C03"), ("f_left_ramp", "C19"), ("f_lower_left", "C22"),
                             ("f_lower_right", "C23"), ("f_right_ramp", "C25"), ("f_red_disc", "C31"),
                             ("f_blue_disc", "C32"), ("c_shaker_motor_optional", "C08")):
            self.assertIs(on, self.machine.coils[name].platform, name)
            self.assertEqual(sam_decode(number), self.proc(self.machine.coils[name]), name)
        for name, number in (("l_start_button", "L01"), ("l_tron_n", "L14"), ("l_shoot_again", "L03"),
                             ("l_left_outlane", "L08"), ("l_left_orbit_disc", "L66")):
            self.assertEqual(sam_decode(number), self.proc(self.machine.lights[name]), name)

    def test_le_only_devices_are_virtual(self):
        on = self.machine.default_platform
        for name in ("c_drop_target_bank", "c_recognizer_motor_relay"):
            self.assertIsNot(on, self.machine.coils[name].platform, name)
        for name in ("s_recog_motor_pos_1", "s_recog_motor_pos_2", "s_recog_motor_pos_3"):
            self.assertIsNot(on, self.machine.switches[name].platform, name)
        for name in ("l_recognizer_pos_1", "l_recognizer_pos_2", "l_recognizer_pos_3"):
            light = self.machine.lights[name]
            self.assertEqual("virtual", light.config["platform"], name)
            self.assertEqual("VirtualLight", type(list(light.hw_drivers.values())[0][0]).__name__)

    def test_every_device_matches_the_pro_map(self):
        """Each P-ROC address is unique and is the LE device's Pro number from the map."""
        pro = _pro_map()
        le = {kind: _load(os.path.join(PACKAGE, f))[section] for kind, f, section in (
            ("switch", "switches.yaml", "switches"), ("coil", "coils.yaml", "coils"), ("lamp", "lights.yaml", "lights"))}
        same = {("coil", 19), ("coil", 25), ("coil", 31), ("coil", 32)}   # ramp and disc flashers: renamed on the Pro
        for kind, devices in (("switch", self.machine.switches), ("coil", self.machine.coils),
                              ("lamp", self.machine.lights)):
            seen = {}
            for device in devices.values():
                if device.name in ("l_left_ramp_tube", "l_right_ramp_tube"):
                    continue
                if kind != "lamp" and device.platform is not self.machine.default_platform:
                    continue
                if kind == "lamp" and device.config.get("platform") == "virtual":
                    continue
                proc = self.proc(device)
                self.assertNotIn(proc, seen, "{} and {} share {}".format(device.name, seen.get(proc), proc))
                seen[proc] = device.name
                cfg = le[kind].get(device.name)
                if cfg is None or not str(cfg["number"]).isdigit():
                    continue
                number = int(cfg["number"])
                expected = number if (kind, number) in same else pro.get((kind, number), number)
                prefix = {"switch": "S", "coil": "C", "lamp": "L"}[kind]
                self.assertEqual(sam_decode("{}{:02d}".format(prefix, expected)), proc, device.name)

    def test_rules_lamps_reach_the_proc(self):
        """The rules address lamps by the ROM's (LE) number: on the Pro, LE lamp 26 SHOOT AGAIN is the light the Pro
        has at 3, and the attract leffs reach the P-ROC's lamp drivers."""
        lamps = self.tron.lamps
        self.assertEqual("l_shoot_again", lamps.lights[26].name)
        self.assertEqual("l_start_button", lamps.lights[65].name)
        self.assertEqual(64, len(lamps.lights))           # every LE lamp; 41 and 44 are NOT USED
        self.advance_time_and_run(2)
        self.sync()
        driven = {c.args[0] for c in self.pinproc.driver_schedule.call_args_list + self.pinproc.driver_disable.call_args_list}
        self.assertTrue(driven & set(LAMP_DRIVERS))

    def test_lower_flashers_follow_the_ramp_flashers(self):
        """The Pro fires 22 / 23 with the ramp flashers 19 / 25 (assets/rom_data/pro/README.md)."""
        self.machine.coils["f_left_ramp"].pulse(48)
        self.sync()
        self.pinproc.driver_pulse.assert_any_call(sam_decode("C19"), 48)
        self.pinproc.driver_pulse.assert_any_call(sam_decode("C22"), 48)
        self.tron.lamps.flasher("f_right_ramp", 50)
        self.sync()
        self.pinproc.driver_pulse.assert_any_call(sam_decode("C25"), 50)
        self.pinproc.driver_pulse.assert_any_call(sam_decode("C23"), 50)

    def test_fiber_optics_off(self):
        """proc_ramp_tubes is 1 here, but a Pro leaves the tubes off unless fiber_optics.yaml enables them."""
        self.advance_time_and_run(.1)
        self.sync()
        for call in self.pinproc.aux_send_commands.call_args_list:
            self.assertFalse([c for c in call.args[1] if isinstance(c, tuple)])
