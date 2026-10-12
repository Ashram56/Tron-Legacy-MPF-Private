"""Operator adjustments, audits and install presets of Tron Legacy LE 1.74 (assets/mpf_package/service_menu.md).

- Adjustments: `os.adj[n]` by ROM adjustment number. The values live in MPF's machine settings
  (config/rom/settings.yaml, generated from the package), stored as persisted machine variables named by
  the setting keys, so an operator change survives power cycles. Unchanged settings hold their factory
  default (not persisted). The ROM ranges come from service_menu.json (min, max, step, value labels).
- Audits: `os.audit(id)` uses the ROM's audit counter ids (audit_add); the service menu numbers them 1-150
  and computes some of them (percentages, averages, totals) from the counters. The counters persist in
  MPF's data file data/tron_audits.yaml (machine.create_data_manager("tron_audits")).
- Install presets (UTILITIES > GO TO INSTALLS MENU) set the adjustments the ROM lists for them;
  INSTALL FACTORY / RESET FACTORY SETTINGS restore every default.
"""
import json
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SERVICE_JSON = os.path.join(ROOT, "assets", "mpf_package", "service_menu.json")
_DATA = None


def service_data():
    """service_menu.json: menus, adjustments (88), audits (150) and install presets, read once."""
    global _DATA
    if _DATA is None:
        with open(SERVICE_JSON, encoding="utf-8") as f:
            data = json.load(f)
        data["adj_by_id"] = {a["id"]: a for a in data["adjustments"]}
        data["audit_by_id"] = {a["id"]: a for a in data["audits"]}
        _DATA = data
    return _DATA


def pct(num, den):
    """The ROM's percentage audits: num * 100 / den, 0 when nothing was counted (FUN_0002e308 and kin)."""
    return num * 100 // den if den else 0


class Adjustments:
    """os.adj: {ROM adj number: value}, read from and written to MPF's settings (persisted machine vars)."""

    def __init__(self, machine, table):
        self.machine = machine
        # {num: (setting key, default)} (os_layer.adjustment_defaults); a config overlay may change a
        # default (config/free_play.yaml: adj 34 on for desktop runs), so MPF's merged settings win
        configured = machine.config.get("settings") or {}
        self.table = table = {num: (key, int(configured.get(key, {}).get("default", default)))
                              for num, (key, default) in table.items()}
        self.info = service_data()["adj_by_id"]
        self.overrides = {}
        variables = machine.variables
        for key, default in table.values():
            # the factory value is a plain (not persisted) machine var, so MPF templates such as the game's
            # balls_per_game: machine.balls_per_game always find one; an operator change persists it
            if not variables.is_machine_var(key) or variables.get_machine_var(key) is None:
                variables.set_machine_var(key, default)

    def default(self, num):
        return self.table[num][1]

    def override(self, num, value):
        """A run-time value that is not stored (live reference scenarios' "adj" command)."""
        self.overrides[num] = int(value)

    def __getitem__(self, num):
        if num in self.overrides:
            return self.overrides[num]
        key, default = self.table[num]
        value = self.machine.variables.get_machine_var(key)
        return default if value is None else int(value)

    def __setitem__(self, num, value):
        """Operator change: stored in MPF's settings machine var and persisted to disk."""
        key = self.table[num][0]
        self.overrides.pop(num, None)
        self.machine.variables.configure_machine_var(key, persist=True)      # as SettingsController does
        self.machine.variables.set_machine_var(key, int(value))
        self.machine.events.post("tron_adjustment_changed", num=num, value=int(value))

    def __iter__(self):
        return iter(sorted(self.table))

    def keys(self):
        return sorted(self.table)

    # ------------------------------------------------------------------ the operator menus

    def label(self, num, value=None):
        """The ROM's text for a value (labels from the ROM's formatting code), else the number."""
        value = self[num] if value is None else value
        labels = self.info.get(num, {}).get("labels") or {}
        return labels.get(str(value), str(value))

    def step(self, num, value, direction):
        """MINUS / PLUS in the adjustment editor: one ROM step, wrapping at the ends of the range."""
        info = self.info[num]
        lo, hi, step = info["min"], info["max"], info["step"] or 1
        value += step * direction
        if value > hi:
            value = lo
        elif value < lo:
            value = hi
        return value

    def menu(self, group):
        """Adjustment numbers of the STANDARD or FEATURE ADJUSTMENTS menu, in the ROM's menu order."""
        rows = [a for a in self.info.values() if a["group"] == group]
        return [a["id"] for a in sorted(rows, key=lambda a: a["menu_order"])]

    def factory_reset(self):
        """INSTALL FACTORY / RESET FACTORY SETTINGS: every adjustment back to its default."""
        for num in self.keys():
            if self[num] != self.default(num):
                self[num] = self.default(num)

    def install(self, preset):
        """UTILITIES > INSTALLS: the preset's adjustment list (empty for the difficulty presets in 1.74)."""
        if preset == "INSTALL FACTORY":
            self.factory_reset()
            return
        for entry in service_data()["install_presets"].get(preset, []):
            self[entry["adj"]] = entry["value"]


# score ranges (audits 30-46 = counters 19-35) and game times in minutes (audits 59-71 = counters 46-58)
SCORE_RANGES = (0, 2e6, 4e6, 6e6, 8e6, 10e6, 12.5e6, 15e6, 17.5e6, 20e6, 25e6, 30e6, 40e6, 50e6, 75e6, 100e6,
                150e6)
SCORE_RANGE_COUNTER = 19
GAME_TIMES = (0, 1, 1.5, 2, 2.5, 3, 3.5, 4, 5, 6, 8, 10, 15)
GAME_TIME_COUNTER = 46
EARNINGS_COUNTERS = (1, 2, 3, 4, 5, 6, 7)      # the counters of the EARNINGS AUDITS menu (reset coin audits)


class Audits:
    """The ROM's audit counters by counter id (audit_add ids), persisted in MPF's data file "tron_audits".
    `extra` keeps the totals the computed audits need (score, play time); the ROM keeps those in OS records."""

    def __init__(self, machine):
        self.machine = machine
        self.info = service_data()["audit_by_id"]
        self.store = machine.create_data_manager("tron_audits")
        data = self.store.get_data() or {}
        self.counts = {int(k): int(v) for k, v in (data.get("counters") or {}).items()}
        self.extra = {k: float(v) for k, v in (data.get("extra") or {}).items()}

    def save(self):
        self.store.save_all(data={"counters": dict(self.counts), "extra": dict(self.extra)})

    # dict-like read access by counter id (the tests and features use .get)
    def get(self, counter, default=None):
        return self.counts.get(counter, default)

    def __getitem__(self, counter):
        return self.counts.get(counter, 0)

    def add(self, counter, n=1):
        self.counts[counter] = self.counts.get(counter, 0) + n
        self.save()

    def add_extra(self, name, value):
        self.extra[name] = self.extra.get(name, 0) + value
        self.save()

    # ------------------------------------------------------------------ menu values (audit numbers 1-150)

    def plays(self):
        return self[17] + self[18]          # TOTAL PLAYS: paid (0x11) + free (0x12) games [FUN_0002e5a4]

    def value(self, number):
        """Audit `number` (1-150) as the menu shows it: a counter, or computed from counters."""
        a = self.info[number]
        if not a["computed"]:
            return self[a["counter"]]
        plays = self.plays()
        replays = sum(self[c] for c in (10, 11, 12, 13))               # FUN_0002e5d4
        computed = {
            2: lambda: pct(self[18], plays),                              # FREE GAME PERCENTAGE
            3: lambda: int(self.extra.get("ball_seconds", 0) // self[8]) if self[8] else 0,   # AVERAGE BALL TIME
            4: lambda: int(self.extra.get("game_seconds", 0) // plays) if plays else 0,       # AVERAGE GAME TIME
            10: lambda: sum(self[c] for c in (2, 3, 4, 5, 6)),             # TOTAL COINS [FUN_0002e4c8]
            11: lambda: sum(self[c] for c in (2, 3, 4, 5, 6)) * 25,        # TOTAL EARNINGS, cents (inferred)
            13: lambda: self[7],                                           # SOFTWARE METER (inferred)
            16: lambda: pct(self[9], self[8]),                             # EXTRA BALL PERCENTAGE
            21: lambda: replays,                                           # TOTAL REPLAYS
            22: lambda: pct(replays, plays),                               # REPLAY PERCENTAGE
            24: lambda: pct(self[14], plays),                              # SPECIAL PERCENTAGE
            27: lambda: pct(self[16], plays),                              # HIGH SCORE PERCENT
            28: lambda: replays + self[14] + self[15] + self[16],          # TOTAL FREE PLAYS [FUN_0002e54c]
            29: lambda: plays,                                             # TOTAL PLAYS
            47: lambda: int(self.extra.get("score_total", 0) // plays) if plays else 0,       # AVERAGE SCORES
            53: lambda: max(0, self[8] - self[40] - self[41]),             # CENTER DRAINS [FUN_0002e484]
            72: lambda: pct(replays, plays),                               # RECENT REPLAY PERCENT (inferred)
        }
        return computed.get(number, lambda: 0)()

    def text(self, number):
        """The value as shown: money, percentages and times formatted."""
        v = self.value(number)
        name = self.info[number]["name"]
        if "PERCENT" in name and self.info[number]["computed"]:
            return "{}%".format(v)
        if number == 11:
            return "${}.{:02d}".format(v // 100, v % 100)
        if number in (3, 4):
            return "{}:{:02d}".format(v // 60, v % 60)
        return "{:,}".format(v)

    def menu(self, group):
        """Audit numbers of the EARNINGS / STANDARD / FEATURE AUDITS screens."""
        return sorted(n for n, a in self.info.items() if a["menu"].split()[0] == group)

    # ------------------------------------------------------------------ resets

    def reset_coin(self):
        """RESET COIN AUDITS: the earnings counters."""
        for c in EARNINGS_COUNTERS:
            self.counts.pop(c, None)
        self.save()

    def reset_game(self):
        """RESET GAME AUDITS: every other counter and the totals behind the averages."""
        self.counts = {c: v for c, v in self.counts.items() if c in EARNINGS_COUNTERS}
        self.extra = {}
        self.save()

    def reset_all(self):
        self.counts, self.extra = {}, {}
        self.save()

    # ------------------------------------------------------------------ game over bookkeeping

    @staticmethod
    def score_range_counter(score):
        """Counter of the score-range audit (audits 30-46) for a final score."""
        i = max(n for n, low in enumerate(SCORE_RANGES) if score >= low)
        return SCORE_RANGE_COUNTER + i

    @staticmethod
    def game_time_counter(seconds):
        """Counter of the game-time audit (audits 59-71) for a game's play time."""
        minutes = seconds / 60.0
        i = max(n for n, low in enumerate(GAME_TIMES) if minutes >= low)
        return GAME_TIME_COUNTER + i


# ---------------------------------------------------------------------------------------------- HD display

# The HD DMD's text glow and size (not in the ROM: docs/rom_differences.md), as percentages:
# {item: (name, stored machine var, live machine var, factory, min, max, step)}. The factory values are
# tools/dmd_mode.gd's defaults (glow 0.8, text scale 0.85).
DISPLAY_ITEMS = {
    1: ("TEXT GLOW", "dmd_text_glow_setting", "dmd_text_glow", 80, 0, 300, 10),
    2: ("TEXT SIZE", "dmd_text_size_setting", "dmd_text_size", 85, 50, 110, 5),
}


class DisplaySettings:
    """DISPLAY ADJUSTMENTS (ADJUSTMENTS menu, added by this game): the HD DMD's text glow and text size, with
    the interface of Adjustments (the adjustment editor uses either). The operator's value persists in
    the stored machine var; the live machine var (not persisted, -1 = the value the display was started
    with: --dmd-text-glow / --dmd-text-scale or their defaults) is what the display (tools/dmd_mode.gd)
    follows, through GMC's machine variable monitor; preview() shows a value being edited there. A value
    stored at its factory default leaves the display's own start value in place."""

    def __init__(self, machine):
        self.machine = machine
        self.info = {num: {"name": spec[0], "min": spec[4], "max": spec[5], "step": spec[6]}
                     for num, spec in DISPLAY_ITEMS.items()}
        for num in DISPLAY_ITEMS:
            self._show(num, self.stored(num))

    def stored(self, num):
        """The operator's value, None when unset or at the factory default."""
        value = self.machine.variables.get_machine_var(DISPLAY_ITEMS[num][1])
        return None if value is None or int(value) < 0 or int(value) == self.default(num) else int(value)

    def _show(self, num, value):
        self.machine.variables.set_machine_var(DISPLAY_ITEMS[num][2], -1 if value is None else int(value))

    def default(self, num):
        return DISPLAY_ITEMS[num][3]

    def __getitem__(self, num):
        value = self.stored(num)
        return self.default(num) if value is None else value

    def __setitem__(self, num, value):
        key = DISPLAY_ITEMS[num][1]
        value = int(value)
        self.machine.variables.configure_machine_var(key, persist=True)
        self.machine.variables.set_machine_var(key, -1 if value == self.default(num) else value)
        self._show(num, self.stored(num))

    def preview(self, num, value):
        """The value being edited on the display; None = back to the stored one."""
        self._show(num, self.stored(num) if value is None else
                   (None if int(value) == self.default(num) else value))

    def keys(self):
        return sorted(DISPLAY_ITEMS)

    def menu(self, group=None):
        return self.keys()

    def label(self, num, value=None):
        value = self[num] if value is None else value
        return "OFF" if num == 1 and value == 0 else "{}%".format(value)

    def step(self, num, value, direction):
        """MINUS / PLUS: one step, stopping at the ends of the range."""
        info = self.info[num]
        return min(info["max"], max(info["min"], value + info["step"] * direction))

    def factory_reset(self):
        for num in self.keys():
            self[num] = self.default(num)
