"""Lamp matrix model: the ROM's game lamp image, flash mask, lamp-matrix effects (leffs) and flashers.

The SAM OS keeps (assets/code/tron_game_decompiled_v2.c, OS functions 0x7d9c-0x9398, compositor
FUN_00007f68):
- the game image 0x3c204 that the rules write with lamp_on / lamp_off / lamp_on_solid / lamp_off_all /
  lamp_toggle, plus the flash mask 0x3c218 (lamp_bit_set): a lamp in the mask blinks while it is on;
- lamp override layers (lamp_layer_create(group, priority)): a mask of lamps and their own image,
  composited over the game image in priority order. The lamp-matrix effects (leff_start 0x87ac,
  table 0x040e23e4) draw through such layers (or the leff image 0x3c224) while their task runs;
- lamp groups (table 0x040e3acc, 0-terminated lamp lists). The ROM table itself is not in the asset
  repo: the groups used by the rules are named here from lights.yaml tags (rom_group_N) and lamps.csv.

Here a running leff is a layer at its ROM priority that plays the leff's captured show
(assets/mpf_package/config/shows/lampfx_NNN_*.yaml, observed in emulation, with its flasher pulses).
The composite drives the MPF lights (key "tron") and is logged as `lamp` events (1-80) exactly like
the ROM reference traces; flasher pulses are logged as `coil` on/off events.

The list-5 lamp rules (rule_obj_init(obj, 5, fn, 0x20)) that redraw inserts from game state on every
rules refresh are registered by the features with os.lamp_update(fn, priority).
"""
import csv
import os
import re

from tron.hw_numbers import pro_companion_flashers, rom_numbers
from tron.os_layer import TICK

LAMP_COUNT = 80
# per-shot inserts, shots 0-5 = left orbit, left ramp, left inner loop, right inner loop, right ramp,
# right orbit (lamps.csv; the ROM's per-shot lamp groups 70-75 for the arrows)
ARROWS = (16, 49, 64, 57, 56, 33)
FLASH_TICKS = 5             # compositor FUN_00007f68 inverts the flash phase every 5 passes (1/tick)
# The reference traces log the lamp outputs as libpinmame reports them: a lamp reads on while it was on
# at any time in about the last 65 ms (a flashing insert: on ~146 ms, off ~16 ms; leff 14 blinking every
# 10 ticks: on ~225 ms, off ~97 ms; anything toggled every 2 ticks reads solid). The trace applies that
# filter; the MPF lights get the unfiltered output.
OFF_DELAY = 0.065
MPF_KEY = "tron"
# The reference traces report a pulsed coil as on until ~0.24 s after its pulse ended (an 18 ms zen
# flasher pulse reads 0.24 s, a 64 ms pulse ~0.33 s, shaker strength 1/2 (75/265 ms) 0.27/0.46 s):
# the `coil` events are logged through the same hold, so back-to-back pulses read as one flash.
COIL_OFF_DELAY = 0.24
WHITE, BLACK = "ffffff", "000000"


def parse_show(path):
    """Minimal reader for the package's generated show files (no YAML library in the venv):
    -> [(seconds, {light: on(bool) or hex color}, {flasher: ms})]."""
    steps = []
    section = None
    for line in open(path, encoding="utf-8"):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = re.match(r"- duration: (\d+)ms", line)
        if m:
            steps.append([int(m.group(1)) / 1000.0, {}, {}])
            section = None
            continue
        m = re.match(r"\s+(lights|flashers):\s*$", line)
        if m:
            section = m.group(1)
            continue
        m = re.match(r"\s+(\S+):\s*'?([0-9a-fA-F]+)(ms)?'?\s*$", line)
        if m and steps and section:
            name, value = m.group(1), m.group(2)
            if section == "flashers":
                steps[-1][2][name] = int(value)
            else:
                steps[-1][1][name] = value.lower()
    return [tuple(s) for s in steps]


class Layer:
    """A lamp override layer (lamp_layer_create): owns `mask`, draws `image` (lamps on) over lower ones."""
    __slots__ = ("prio", "mask", "image", "seq", "name")

    def __init__(self, prio, mask=(), name=None):
        self.prio = prio
        self.mask = set(mask)
        self.image = set()
        self.seq = 0
        self.name = name


class ShowPlayer:
    """Plays a parsed show on a layer (lamps), MPF RGB lights (tubes) and flashers."""

    def __init__(self, lamps, steps, layer=None, loops=0, tokens=None, on_end=None, rgb=False, owner=None):
        self.lamps = lamps
        self.owner = owner          # the leff id whose show this is (flasher arbitration)
        self.steps = steps
        self.layer = layer
        self.loops = loops
        self.tokens = tokens or {}
        self.on_end = on_end
        self.rgb = rgb
        self.index = 0
        self.handle = None
        self.done = False
        self._step()

    def _resolve(self, name):
        if name.startswith("("):
            return self.tokens.get(name.strip("()"), ())
        return (name,)

    def _step(self):
        self.handle = None
        if self.index >= len(self.steps):
            if self.loops == -1 and self.steps:
                self.index = 0
            else:
                self.done = True
                if self.on_end:
                    self.on_end()
                return
        seconds, lights, flashers = self.steps[self.index]
        self.index += 1
        lm = self.lamps
        for name, value in lights.items():
            for target in self._resolve(name):
                if self.rgb:
                    lm.rgb(target, value)
                    continue
                for n in lm.lamp_numbers(target):
                    if value != BLACK:
                        self.layer.image.add(n)
                    else:
                        self.layer.image.discard(n)
        for name, ms in flashers.items():
            lm.flasher(name, ms, owner=self.owner)
        if lights and not self.rgb:
            lm.changed()
        self.handle = lm.clock.schedule_once(self._step, max(seconds, 0.001))

    def stop(self):
        if self.handle:
            self.lamps.clock.unschedule(self.handle)
            self.handle = None
        self.done = True


class LeffTask:
    """A lamp-matrix effect drawn by code (the leffs whose show is "state display" or that follow live
    state): the ROM leff function as a task with its own layer. fn(task) draws on task.layer and
    continues with task.sleep(ticks, next_fn); task.end() ends the leff (its layer is released)."""

    def __init__(self, lamps, leff_id, layer):
        self.lamps = lamps
        self.leff_id = leff_id
        self.layer = layer
        self.handle = None
        self.data = {}
        self.children = []

    def spawn(self, fn, priority):
        """task_spawn_child: a child task with its own layer (freed with the leff)."""
        child = LeffTask(self.lamps, self.leff_id, self.lamps.layer_create(priority, name=self.layer.name))
        self.children.append(child)
        fn(child)
        return child

    def sleep(self, ticks, fn):
        def run():
            self.handle = None
            fn(self)
        self.handle = self.lamps.clock.schedule_once(run, max(ticks, 1) * TICK)

    def release(self, lamp):
        """lampgroup_bit_clear(group, layer mask): the lamp shows what is underneath again."""
        if lamp in self.layer.mask:
            self.layer.mask.discard(lamp)
            self.layer.image.discard(lamp)
            self.lamps.changed()

    def set(self, lamp, on):
        self.layer.mask.add(lamp)
        if on:
            self.layer.image.add(lamp)
        else:
            self.layer.image.discard(lamp)
        self.lamps.changed()

    def toggle(self, lamp):
        self.set(lamp, lamp not in self.layer.image)

    def end(self):
        """The leff function returned: its task ends (display.Leffs frees its outputs)."""
        self.lamps._leff_show_done(self.leff_id)
        self.lamps.os.leffs._ended(self.leff_id)

    def stop(self):
        if self.handle:
            self.lamps.clock.unschedule(self.handle)
            self.handle = None
        for child in self.children:
            child.stop()
            self.lamps.layer_free(child.layer)
        self.children = []


class Lamps:
    """The lamp matrix as the ROM keeps it. `in` / add / discard keep the old set interface
    (os.lamps: inserts the rules read back) as lamp_test / lamp_on_solid / lamp_off_all."""

    def __init__(self, os_):
        self.os = os_
        self.machine = os_.machine
        self.clock = os_.machine.clock
        self.image = set()          # game image 0x3c204: lamps on
        self.flash = set()          # flash mask 0x3c218
        self.layers = []            # override layers, composited in (priority, creation) order
        self._seq = 0
        self.out = [0] * (LAMP_COUNT + 1)       # last output logged (filtered as libpinmame reports it)
        self.raw = [0] * (LAMP_COUNT + 1)       # composite output (MPF lights)
        self._off_pending = {}
        self._off_since = [0.0] * (LAMP_COUNT + 1)
        self.flash_off = False      # flash phase: True while flashing lamps are blanked
        self._flash_handle = None
        self._dirty = False
        self.leff_players = {}      # leff id -> ShowPlayer
        self.tube_players = {}      # tube show id -> ShowPlayer
        self.code_leffs = {}        # leff id -> (layer priority, fn(LeffTask)): leffs drawn by code
        self.rules = []             # list-5 lamp rules: (priority, seq, fn)
        root = os.path.join(self.machine.machine_path, "..", "assets", "mpf_package")
        self.show_dir = os.path.join(root, "config", "shows")
        self._shows = {}
        self.leff_info = {}         # leff id -> (show name, loops, priority)
        with open(os.path.join(root, "lamp_effects.csv"), encoding="utf-8") as f:
            for row in csv.DictReader(f):
                self.leff_info[int(row["leff"])] = (row["show"], int(row["loops"] or 0), int(row["priority"] or 0))
        self.names = {}             # MPF light name -> lamp number (lamp matrix only)
        self.lights = {}            # lamp number -> MPF light
        self.groups = {}            # light tag (rom_group_N) -> lamp numbers
        rom_lamps = rom_numbers(self.machine, "lights")      # the ROM's lamp numbers, on any platform or machine
        for light in getattr(self.machine, "lights", {}).values():
            num = rom_lamps.get(light.name)
            if num is not None:
                self.names[light.name] = num
                self.lights[num] = light
                for tag in light.tags:
                    self.groups.setdefault(tag, []).append(num)
        self.coil_numbers = {}
        self._coil_until = {}       # flasher coil -> end of its current pulse
        rom_coils = rom_numbers(self.machine, "coils")
        for coil in getattr(self.machine, "coils", {}).values():
            if coil.name in rom_coils:
                self.coil_numbers[coil.name] = rom_coils[coil.name]
        pro_companion_flashers(self.machine)
        self._start_flash()

    # ------------------------------------------------------------------ game image (ROM names)

    def lamp_on(self, n):
        """lamp_on(n, 0x3c204, 0xff): on; a lamp in the flash mask keeps flashing."""
        self.image.add(n)
        self.changed()

    def lamp_off(self, n):
        """lamp_off(n, 0x3c204, 0xff): off (the flash bit stays)."""
        self.image.discard(n)
        self.changed()

    def lamp_on_solid(self, n):
        """lamp_on_solid [0x83f4]: on, flash bit cleared."""
        self.image.add(n)
        self.flash.discard(n)
        self.changed()

    def lamp_off_all(self, n):
        """lamp_off_all [0x82b0]: off, flash bit cleared."""
        self.image.discard(n)
        self.flash.discard(n)
        self.changed()

    def lamp_flash(self, n):
        """lamp_on + lamp_bit_set(n, 0x3c218) (FUN_01015094(n, 1)): flashing."""
        self.image.add(n)
        self.flash.add(n)
        self.changed()

    def lamp_toggle(self, n):
        if n in self.image:
            self.image.discard(n)
        else:
            self.image.add(n)
        self.changed()

    def lamp_test(self, n):
        return n in self.image

    def lamp_flashing(self, n):
        return n in self.image and n in self.flash

    def lamp_set(self, n, state):
        """state: 0 off, 1 solid on, 2 flashing (the three states the lamp rules draw)."""
        if state == 2:
            self.lamp_flash(n)
        elif state:
            self.lamp_on_solid(n)
        else:
            self.lamp_off_all(n)

    def lamp_state(self, n):
        return 0 if n not in self.image else 2 if n in self.flash else 1

    def clear(self):
        """FUN_00007eb8: game image, flash mask and leff images cleared (game start / end)."""
        self.image.clear()
        self.flash.clear()
        self.changed()

    # old set interface (os.lamps)
    def __contains__(self, n):
        return self.lamp_test(n)

    def add(self, n):
        self.lamp_on_solid(n)

    def discard(self, n):
        self.lamp_off_all(n)

    # ------------------------------------------------------------------ groups, layers

    def group(self, name):
        """Lamps of a ROM lamp group (lights.yaml tag rom_group_N) or of a light/lamp list."""
        if isinstance(name, int):
            return list(self.groups.get("rom_group_{}".format(name), ()))
        return list(self.groups.get(name, ()))

    def lamp_numbers(self, target):
        if isinstance(target, int):
            return (target,)
        if target in self.names:
            return (self.names[target],)
        return tuple(self.groups.get(target, ()))

    def layer_create(self, prio, mask=(), name=None):
        """lamp_layer_create(group, priority): a new layer on top of the ones with the same priority."""
        layer = Layer(prio, mask, name)
        self._seq += 1
        layer.seq = self._seq
        self.layers.append(layer)
        self.layers.sort(key=lambda la: (la.prio, la.seq))
        self.changed()
        return layer

    def layer_free(self, layer):
        if layer in self.layers:
            self.layers.remove(layer)
            self.changed()

    # ------------------------------------------------------------------ lamp-matrix effects

    def show(self, name):
        if name not in self._shows:
            path = os.path.join(self.show_dir, name + ".yaml")
            self._shows[name] = parse_show(path) if os.path.exists(path) else []
        return self._shows[name]

    def leff_code(self, leff_id, fn, priority=None):
        """Draw leff `leff_id` with code instead of its captured show (fn(LeffTask), layer `priority`,
        default the leff's ROM priority)."""
        self.code_leffs[leff_id] = (priority, fn)

    def leff_play(self, leff_id, lamp=None):
        """A leff task started (display.Leffs accepted it): play its captured show on a layer at the ROM
        priority. `lamp` is the lamp (or lamp list / light tag) a caller passes to the token effects."""
        self.leff_end(leff_id)
        name, loops, prio = self.leff_info.get(leff_id, ("", 0, 0))
        if leff_id in self.code_leffs:
            layer_prio, fn = self.code_leffs[leff_id]
            layer = self.layer_create(prio if layer_prio is None else layer_prio, name="leff_{}".format(leff_id))
            task = LeffTask(self, leff_id, layer)
            task.data["lamp"] = lamp
            self.leff_players[leff_id] = (task, layer)
            fn(task)
            return
        steps = self.show(name) if name else []
        if not steps:
            return
        tokens = {}
        mask = set()
        if lamp is not None:
            targets = lamp if isinstance(lamp, (list, tuple, set)) else (lamp,)
            tokens["lamp"] = tokens["lamps"] = [t for t in targets]
        for _, lights, _ in steps:
            for light in lights:
                for target in (tokens.get(light.strip("()"), ()) if light.startswith("(") else (light,)):
                    mask.update(self.lamp_numbers(target))
        layer = self.layer_create(prio, mask, name="leff_{}".format(leff_id))
        self.leff_players[leff_id] = (ShowPlayer(self, steps, layer, loops, tokens, owner=leff_id,
                                                 on_end=lambda: self._leff_show_done(leff_id)), layer)

    def _leff_show_done(self, leff_id):
        # a show that plays once ends with its task: the layer is released (display.Leffs keeps the
        # leff's own length for the priority bookkeeping)
        entry = self.leff_players.pop(leff_id, None)
        if entry:
            if isinstance(entry[0], LeffTask):
                entry[0].stop()
            self.layer_free(entry[1])

    def leff_end(self, leff_id):
        entry = self.leff_players.pop(leff_id, None)
        if entry:
            entry[0].stop()
            self.layer_free(entry[1])

    def leff_lamps_end(self):
        for leff_id in list(self.leff_players):
            self.leff_end(leff_id)

    # ------------------------------------------------------------------ tubes and flashers

    def tube_play(self, show_id):
        """Ramp tube show (display.Tubes accepted it): its show on the two RGB tube lights."""
        self.tube_end(show_id)
        steps = self.show("leff_{:03d}".format(show_id))
        if steps:
            loops = -1 if self.os.tubes.info.get(show_id, (0, 0, "loop", 0))[2] != "once" else 0
            self.tube_players[show_id] = ShowPlayer(self, steps, loops=loops, rgb=True,
                                                    on_end=lambda: self.tube_players.pop(show_id, None))

    def tube_end(self, show_id):
        player = self.tube_players.pop(show_id, None)
        if player:
            player.stop()

    def rgb(self, light_name, value):
        light = getattr(self.machine, "lights", {}).get(light_name)
        if light is not None:
            light.color(value.lstrip("#"), key=MPF_KEY)

    def flasher(self, name, ms=30, owner=None):
        """coil_pulse(coil, time) for a flasher: pulse the MPF coil, log coil on/off like the ROM traces.
        owner: the leff pulsing it. While a running leff with a higher priority uses the same flasher,
        a lower leff's pulses do not reach it (the ROM's flasher ownership: traces/portal_multiball.jsonl
        35.4 s, the disc flashers of leff 167 stop while leff 169 runs)."""
        if owner is not None and self.os.leffs.flasher_outranked(owner, name):
            return
        coil = getattr(self.machine, "coils", {}).get(name)
        num = self.coil_numbers.get(name)
        if coil is not None:
            try:
                coil.pulse(int(ms))
            except Exception:       # noqa: BLE001 (a disabled driver in a test machine)
                pass
        if num is not None:
            self.coil_log(num, ms)

    def coil_log(self, num, ms):
        """Log a `coil` on/off pair for a driver on for `ms`, through the reference traces' output hold."""
        # the driver stays on through back-to-back pulses: one on/off pair, as the traces log the driver
        now = self.clock.get_time()
        until = now + ms / 1000.0 + COIL_OFF_DELAY
        if self._coil_until.get(num, 0) <= now:
            self.os.trace.log("coil", coil=num, on=1)
            self._coil_until[num] = until
            self.clock.schedule_once(lambda: self._coil_off(num), until - now)
        else:
            self._coil_until[num] = max(self._coil_until[num], until)

    def _coil_off(self, num):
        left = self._coil_until.get(num, 0) - self.clock.get_time()
        if left > 0.0005:
            self.clock.schedule_once(lambda: self._coil_off(num), left)
            return
        self.os.trace.log("coil", coil=num, on=0)

    # ------------------------------------------------------------------ list-5 lamp rules

    def add_rule(self, fn, priority=0):
        self._seq += 1
        self.rules.append((-priority, -self._seq, fn))       # equal priority: newest first
        self.rules.sort(key=lambda r: (r[0], r[1]))

    def run_rules(self):
        for _, _, fn in self.rules:
            fn()

    # ------------------------------------------------------------------ output

    def _start_flash(self):
        """Flash phase: flashing lamps are blanked every other FLASH_TICKS ticks."""
        def phase():
            self.flash_off = not self.flash_off
            self._start_flash()
            if self.flash & self.image:
                self._flush()
        self._flash_handle = self.clock.schedule_once(phase, FLASH_TICKS * TICK)

    def changed(self):
        if not self._dirty:
            self._dirty = True
            self.clock.schedule_once(self._flush, 0)

    def composite(self, n):
        on = n in self.image and not (self.flash_off and n in self.flash)
        for layer in self.layers:
            if n in layer.mask:
                on = n in layer.image
        return on

    def _flush(self):
        self._dirty = False
        for n in range(1, LAMP_COUNT + 1):
            state = 1 if self.composite(n) else 0
            if state == self.raw[n]:
                continue
            self.raw[n] = state
            light = self.lights.get(n)
            if light is not None:
                light.color(WHITE if state else BLACK, key=MPF_KEY)
            if state:
                if not self.out[n]:
                    self.out[n] = 1
                    self.os.trace.log("lamp", lamp=n, state=1)
            else:
                self._off_since[n] = self.clock.get_time()
                if self.out[n] and n not in self._off_pending:
                    self._off_pending[n] = self.clock.schedule_once(lambda n=n: self._off(n), OFF_DELAY)

    def _off(self, n):
        """The filtered output goes off once the lamp has stayed off for OFF_DELAY."""
        self._off_pending.pop(n, None)
        if self.raw[n] or not self.out[n]:
            return
        wait = self._off_since[n] + OFF_DELAY - self.clock.get_time()
        if wait > 0.001:
            self._off_pending[n] = self.clock.schedule_once(lambda: self._off(n), wait)
            return
        self.out[n] = 0
        self.os.trace.log("lamp", lamp=n, state=0)
