"""P-ROC only hardware (hw_proc.yaml overlay): the two ramp light tubes on the SAM IO board's aux bus.

The P-ROC drives SAM's coils and lamp matrix itself, but the ramp light tubes (Tron LE's fiber optic ramps,
board 511-6927-01) hang off the IO board's aux bus, which MPF has no device for. The ROM's tube driver
(assets/io/README.md, tube_refresh 0x000874) does this every 250 us IO tick:
- write the colour's bit plane to AUX_DRV (IO address 6): R = bit 5, G = bit 4, B = bit 3;
- pulse the tube's strobe low then high in the strobe latch (IO address 0xB, shadow 0x3c758): left tube
  0x10, right tube 0x20; the latch idles at 0xFE (all strobes high, bit 0 low: GI on);
- one bit plane per tick, plane k for 2^k ticks: 4-bit colour (0-15) by binary-coded modulation.

Here the same sequence runs as a looping P-ROC aux port program (the mechanism MPF uses for WPC alphanumeric
displays). pypinproc has the two SAM aux writes this needs (github.com/preble/pypinproc, pypinproc.cpp,
pinproc_aux_command_output_primary/_secondary): for sternSAM "primary" is PRDriverAuxPrepareOutput(data, 0,
enables 6, mux 1) = AUX_DRV and "secondary" enables 11 = the strobe latch. The lights l_left_ramp_tube /
l_right_ramp_tube stay virtual MPF lights that shows and tron/lamps.py drive as before; this module polls
their colour and rewrites the program when the 4-bit colour changes.

Off unless the machine variables proc_ramp_tubes (hw_proc_le.yaml: the aux bus writes are unverified on a real machine,
docs/hardware.md, "Ramp light tubes") and fiber_optics (1 on an LE, 0 on a Pro unless fiber_optics.yaml enables it) are
both 1. With the virtual platform (tests) this does nothing.
"""
from mpf.core.custom_code import CustomCode

STROBE_IDLE = 0xFE            # every strobe high, bit 0 (GI relay) low = GI on: the bus capture in assets/io/README.md
TUBES = (("l_left_ramp_tube", 0x10), ("l_right_ramp_tube", 0x20))
RGB_BITS = (5, 4, 3)          # AUX_DRV bits of R, G, B
TICK_US = 250                 # the ROM's IO interrupt tick: plane k shows for 2^k ticks (15-tick frame, 3.75 ms)
POLL_HZ = 60


def tube_colour(light):
    """Current colour of an MPF RGB light as the ROM's 4-bit (0-15) channels, fades included."""
    channels = []
    for colour in ("red", "green", "blue"):
        drivers = light.hw_drivers.get(colour) or []
        level = drivers[0].current_brightness if drivers else 0.0
        channels.append(max(0, min(15, int(round(level * 15)))))
    return tuple(channels)


def aux_program(pinproc, colours):
    """Aux port commands for one 15-tick frame. colours: one (r, g, b) 0-15 tuple per entry of TUBES."""
    commands = []
    for plane in range(4):
        for (_, strobe), rgb in zip(TUBES, colours):
            data = 0
            for value, bit in zip(rgb, RGB_BITS):
                if value >> plane & 1:
                    data |= 1 << bit
            commands.append(pinproc.aux_command_output_primary(data, 0, 0))                  # AUX_DRV (IO 0x6)
            commands.append(pinproc.aux_command_output_secondary(STROBE_IDLE & ~strobe, 0, 0))  # strobe low (IO 0xB)
            commands.append(pinproc.aux_command_output_secondary(STROBE_IDLE, 0, 0))         # and high: latch
        commands.append(pinproc.aux_command_delay(TICK_US << plane))
    return commands


class ProcHardware(CustomCode):

    def on_load(self):
        self.platform = None
        self.aux_index = None
        self.colours = None
        var = self.machine.variables.get_machine_var
        if not var("proc_ramp_tubes") or var("fiber_optics") == 0:
            return
        self.machine.events.add_handler("init_phase_5", self._start)

    def _start(self, **kwargs):
        del kwargs
        platform = self.machine.default_platform
        aux_port = getattr(platform, "aux_port", None)
        lights = getattr(self.machine, "lights", {})
        if aux_port is None or any(name not in lights for name, _ in TUBES):
            self.warning_log("ramp tubes: no P-ROC aux port or no tube lights; tubes not driven")
            return
        self.platform = platform
        self.aux_index = aux_port.reserve_index()
        self.machine.clock.schedule_interval(self._poll, 1 / POLL_HZ)
        self._poll()

    def _poll(self):
        lights = self.machine.lights
        colours = tuple(tube_colour(lights[name]) for name, _ in TUBES)
        if colours == self.colours:
            return
        self.colours = colours
        self.platform.aux_port.update(self.aux_index, aux_program(self.platform.pinproc, colours))
