"""Visual Pinball X only (hw_vpx.yaml overlay): make MPF's virtual_pinball platform answer like VPinMAME.

The VPW Tron table was written for PinMAME. Its script (and VPinMAME's core.vbs / sam.vbs, which it loads) reads
the controller the way VPinMAME answers, so the TronMPF.Controller COM bridge (scripts/vpx_bridge.py) forwards
each call to MPF's virtual_pinball platform over BCP ("vpcom_bridge" commands, port 5051), and this module fixes
the answers where MPF 0.80's platform differs from VPinMAME:

- Switches MPF does not know (coin slots 2 and 3, the EOS and upper flipper buttons) are ignored instead of
  raising: an error in a Controller.Switch call stops the table's script.
- Solenoids are reported as VPinMAME does with modulated solenoids on (the table sets UseVPMModSol): number
  and 0 or 255. A pulse is reported even when it ends between two polls (the table polls once a frame).
- The hardware rules (flippers) drive their coils like the SAM CPU does: the flipper coil follows its button
  while MPF has the rule on. Solenoid 33 is on while any flipper rule is on: that is the input of the table's
  fast flips (sam.vbs cvpmFFlipsSAM: SolCallback(33) switches the flippers from ROM to button control), so
  the flippers react without a round trip to MPF, and stop when MPF disables them (tilt, ball end, game over).
- Coin door open (End key, switch -4): the ROM drives no coil but the optional coil 24 while the door interlock
  has cut the 50 V / 20 V (IO interrupt 0x12070 writes shadow & mask 0x3b984 while RAM 0x3727c & 3 != 3), so
  every other solenoid reads 0 and solenoid 33 (the fast flips) is off until the door closes.
- Stop: the table closed; MPF quits too when the bridge started it.
- Lamps are numbered as in PinMAME (1-80, 0/1), and the ramp tubes' colour bits are lamps 101-106 as PinMAME's
  SAM driver numbers them (src/wpc/sam.c, SAM_GAME_TRON: strobe 0x10 -> 101-103, strobe 0x20 -> 104-106, each
  blue, green, red). Those six are 0-255: the table only uses them as RGB() colour values. They stay 0 while the
  machine var fiber_optics is 0 (a Pro, hw_vpx_pro.yaml, unless enabled).

MPF's platform classes have __slots__, so the methods are replaced on the classes; they fall back to MPF's own
code for any platform this module did not attach to.
"""
import logging

from mpf.core.custom_code import CustomCode
from mpf.platforms.virtual_pinball import virtual_pinball as vp

FLIPPER_COILS = ("15", "16", "12")     # c_left_flipper, c_right_flipper, c_upper_left_flipper
FLIPPERS_ON_SOLENOID = 33              # sam.vbs: SolCallback(33) = "vpmFFlipsSAM.RomControl = not"
MAX_SOLENOID = 32
POWERED_WITH_DOOR_OPEN = (24,)         # coil descriptor flag 0x2 (assets/rom_data/io/coils.csv): OPTIONAL COIL
TUBE_LAMPS = range(101, 107)           # hw_vpx.yaml: the ramp tubes' channels, reported 0-255

_ADAPTERS = {}          # id(platform) -> VpxAdapter
_ORIGINAL = {}


def _number(value):
    """VBScript passes switch numbers as ints (or strings); the platform keys them by str."""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value)


def _flag(value):
    """VBScript's True is -1; anything non-zero is closed."""
    if isinstance(value, str):
        return value.strip().lower() not in ("", "0", "false")
    return bool(value)


class VpxAdapter:

    """VPinMAME-style answers for one virtual_pinball platform."""

    def __init__(self, machine, platform):
        self.machine = machine
        self.platform = platform
        self.log = logging.getLogger("VPX bridge")
        self.unknown = set()
        self.pulsed = set()             # drivers pulsed since the last ChangedSolenoids, by number
        self.last_sol = {}
        self.last_lamp = {}

    # ------------------------------------------------------------------ switches
    def switch_known(self, number):
        if number in self.platform._switches:
            return True
        if number not in self.unknown:
            self.unknown.add(number)
            self.log.info("table switch %s is not an MPF switch, ignored", number)
        return False

    def set_switch(self, number, value):
        number, value = _number(number), _flag(value)
        if not self.switch_known(number):
            return True
        switch = self.platform._switches[number]
        switch.state = value
        self.machine.switch_controller.process_switch_by_num(state=1 if value else 0, num=number,
                                                             platform=self.platform)
        self.apply_rules(switch, value)
        return True

    def get_switch(self, number):
        number = _number(number)
        if not self.switch_known(number):
            return False
        switch = self.platform._switches[number]
        return bool(switch.state) != bool(switch.config.invert)

    def pulse_switch(self, number):
        self.set_switch(number, True)
        self.set_switch(number, False)
        return True

    def apply_rules(self, hw_switch, active):
        """What the SAM CPU does with a flipper button: fire the coil and hold it while the button is down."""
        for (rule_switch, driver), hold in list(self.platform.rules.items()):
            if rule_switch is not hw_switch:
                continue
            if active:
                if hold:
                    driver._state = True
                else:
                    pulse_ms = driver.config.default_pulse_ms or 10
                    driver._state = self.machine.clock.get_time() + pulse_ms / 1000.0
                    self.pulsed.add(driver.number)
            elif hold:
                driver._state = False

    # ------------------------------------------------------------------ outputs
    def door_open(self):
        door = self.machine.switches.get("s_coin_door_open")
        return bool(door) and self.machine.switch_controller.is_active(door)

    def flippers_on(self):
        return any(driver.number in FLIPPER_COILS for (_, driver) in self.platform.rules)

    def changed_solenoids(self):
        states = {}
        for number, driver in self.platform._drivers.items():
            if not number.isdigit() or not 1 <= int(number) <= MAX_SOLENOID:
                continue        # the ticket outputs (aux1-3) are not PinMAME solenoids
            states[int(number)] = driver.state or number in self.pulsed
        self.pulsed.clear()
        states[FLIPPERS_ON_SOLENOID] = self.flippers_on()
        if self.door_open():
            states = {n: v and n in POWERED_WITH_DOOR_OPEN for n, v in states.items()}
        changed = []
        for number in sorted(states):
            value = 255 if states[number] else 0
            if self.last_sol.get(number, 0) != value:
                self.last_sol[number] = value
                changed.append([number, value])
        return changed

    def lamp_levels(self):
        levels = {}
        fiber_optics = self.machine.variables.get_machine_var("fiber_optics") != 0    # machine_pro.yaml: off on a Pro
        for light in self.platform._lights.values():
            if light.subtype != "matrix" or not light.hw_number.isdigit():
                continue
            number, level = int(light.hw_number), light.current_brightness
            if number in TUBE_LAMPS:
                levels[number] = max(0, min(255, int(round(level * 255)))) if fiber_optics else 0
            else:
                levels[number] = 1 if level > 0.5 else 0
        return levels

    def changed_lamps(self):
        changed = []
        for number, value in sorted(self.lamp_levels().items()):
            if self.last_lamp.get(number, 0) != value:
                self.last_lamp[number] = value
                changed.append([number, value])
        return changed

    def stop(self, quit_game):
        """The table closed. When the bridge started the game for it, the game quits too (run.py then stops Godot)."""
        self.log.info("the table closed%s", ", quitting" if quit_game else "")
        if quit_game:
            self.machine.stop("VPX table closed")
        return True

    def pulse_driver(self, driver):
        self.pulsed.add(driver.number)


def _adapter(platform):
    return _ADAPTERS.get(id(platform))


def _wrap(name, method):
    original = _ORIGINAL.setdefault(name, getattr(vp.VirtualPinballPlatform, name, None))

    def patched(self, *args, **kwargs):
        adapter = _adapter(self)
        if adapter is None:
            if original is None:
                raise AttributeError(name)
            return original(self, *args, **kwargs)
        return method(adapter, *args, **kwargs)
    patched.__name__ = name
    setattr(vp.VirtualPinballPlatform, name, patched)


def _install_class_patches():
    if _ORIGINAL:
        return
    _wrap("vpx_set_switch", lambda a, number, value: a.set_switch(number, value))
    _wrap("vpx_get_switch", lambda a, number: a.get_switch(number))
    _wrap("vpx_switch", lambda a, number: a.get_switch(number))
    _wrap("vpx_pulsesw", lambda a, number: a.pulse_switch(number))
    _wrap("vpx_changed_solenoids", lambda a: a.changed_solenoids())
    _wrap("vpx_changed_lamps", lambda a: a.changed_lamps())
    _wrap("vpx_get_mech", lambda a, number: 0)
    _wrap("vpx_mech", lambda a, number: 0)
    _wrap("vpx_stop", lambda a, quit=False: a.stop(quit))

    driver_pulse = vp.VirtualPinballDriver.pulse

    def pulse(self, pulse_settings):
        driver_pulse(self, pulse_settings)
        for adapter in _ADAPTERS.values():
            if adapter.platform._drivers.get(self.number) is self:
                adapter.pulse_driver(self)
    vp.VirtualPinballDriver.pulse = pulse


class VpxHardware(CustomCode):

    def on_load(self):
        platform = self.machine.hardware_platforms.get("virtual_pinball")
        if platform is None:
            self.warning_log("hw_vpx: the virtual_pinball platform is not loaded, nothing to adapt")
            return
        _install_class_patches()
        _ADAPTERS[id(platform)] = VpxAdapter(self.machine, platform)
        self.machine.events.add_handler("shutdown", self._detach, platform=platform)

    @staticmethod
    def _detach(platform, **kwargs):
        del kwargs
        _ADAPTERS.pop(id(platform), None)
