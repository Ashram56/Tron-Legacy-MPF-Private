"""The operator service menu of Tron Legacy LE 1.74 (assets/mpf_package/service_menu.md / .json), as the MPF
mode "tron_service" (game/modes/tron_service).

The coin-door buttons drive it: SELECT enters it from attract mode and opens an item, MINUS / PLUS move or
change a value, BACK leaves. The tree, item texts and visibility conditions are the ROM's own tables
(service_menu.json); every menu ends with its return item, EXIT SERVICE MENU and DISPLAY HELP SCREEN.
The screens operate the hardware through MPF (switch, coil, flash lamp, lamp, trough, knocker, sound and
motor tests), show and reset the persistent audits, edit the 88 adjustments (MPF settings, persisted),
run the install presets and resets, and set the date and time.

The DMD shows each screen as the ROM draws it (tron/rom_draw.py: ROM fonts at the ROM's dot positions and
the ROM's images), on the service slide (game/slides/service.tscn, tron/service_screen.gd,
MediaBridge.service_show):
- SELECT in attract mode shows the service entry screen of deff 3 [0x01037a6c, FUN_01037994]: the version
  line and SERVICE MENU / PRESS 'SELECT' TO CONTINUE; SELECT again opens the main menu.
- A menu [FUN_01037588] is a row of 17 x 23 icons (ROM images 0-163, two per item: the selected item's
  image n, the others n + 1) centred at the top, with the selected item's text in font 2 on row 30. A menu
  wider than the display shows 5 icons between the MORE arrows (images 12 and 13) and scrolls.
- The test, audit and adjustment screens follow their ROM draw code (addresses at each screen class).
The texts also go to the MPF event "tron_service_display" (line0-line2), which the tests read.
"""
import datetime
import os
import re

from mpf.core.mode import Mode

from tron import rom_draw as rd
from tron.hw_numbers import sam_number
from tron.settings import service_data

BUTTONS = {"s_service_back": "back", "s_service_minus": "minus", "s_service_plus": "plus",
           "s_service_select": "select"}
# the menus' "shown_only_if" condition functions [ROM addresses]
CYCLE_SECONDS = 1.0          # cycling coil / flash lamp tests: one output per second
BLINK_SECONDS = 0.5          # lamp tests blink
CHARSET = " ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!?.,'-&"
CUSTOM_MESSAGE_LEN = 16
CUSTOM_PRICING_MAX = 10
LOCK_KEY = "service"
LIGHT_PRIORITY = 1000000

# ROM draw constants
TITLE_FONTS = (15, 12, 8, 2, 0)   # text_draw_msg_fit lists of the big titles (SERVICE MENU is font 15: deff 3 capture)
SMALL_FONTS = (2, 0)              # the PRESS 'SELECT' lines (font 2 in the deff 3 capture)
CONTINUE = "PRESS 'SELECT' TO CONTINUE"
CANCEL = "PRESS 'BACK' TO CANCEL"
VERSION = ("TRON L.E.", "V1.74", "SYS. 1.63", "HDW. 1")      # deff 3 reference capture
ICON_W = 17                       # every menu icon and the MORE arrows are 17 dots wide
MORE_LEFT, MORE_RIGHT = 12, 13
# Menu icons by item text (ROM images 0-163 and the game's 1429-1438, read off the images' labels): the
# selected item's image; the image after it is the same icon dimmed. The item table (0x040f4574) that holds
# the numbers is not in the package. FEATURE AUDITS / ADJUSTMENTS (added by the game) have no icon of their
# own among the images: the S.P.I. ones of their standard twins are used.
ICONS = {
    "GO TO DIAGNOSTICS MENU": 0, "GO TO AUDITS MENU": 2, "GO TO ADJUSTMENTS MENU": 4, "GO TO UTILITIES MENU": 6,
    "GO TO TOURNAMENT MENU": 8, "GO TO REDEMPTION MENU": 10,
    "GO TO SWITCH MENU": 20, "GO TO COIL MENU": 22, "GO TO LAMP MENU": 24, "GO TO FLASH LAMPS MENU": 26,
    "BALL TROUGH TEST": 28, "TECHNICIAN ALERTS": 30, "KNOCKER TEST": 32, "SOUND/SPEAKER TEST": 34,
    "BEGIN BURN-IN": 36, "DOT MATRIX TEST": 38, "DISPLAY SOFTWARE ERRORS": 40,
    "SWITCH TEST": 50, "ACTIVE SWITCH TEST": 52, "SWITCH ALERTS": 56,
    "SINGLE COIL TEST": 58, "CYCLING COIL TEST": 60,
    "SINGLE LAMP TEST": 62, "TEST ALL LAMPS": 64, "LAMP ROW TEST": 66, "LAMP COLUMN TEST": 68,
    "SINGLE FLASH LAMP TEST": 72, "CYCLING FLASH LAMP TEST": 74,
    "COIL FLOW CHART": 76, "SWITCH FLOW CHART": 78, "LAMP FLOW CHART": 80,
    "EARNINGS AUDITS": 82, "STANDARD AUDITS": 84, "FEATURE AUDITS": 84, "DUMP AUDITS TO USB": 86,
    "STANDARD ADJUSTMENTS": 88, "FEATURE ADJUSTMENTS": 88,
    "GO TO INSTALLS MENU": 90, "ENTER CUSTOM MESSAGE": 92, "SET CUSTOM PRICING": 94, "SET DATE/TIME": 96,
    "GO TO RESETS MENU": 98, "GO TO SERIAL MENU": 100, "GO TO USB MENU": 102,
    "INSTALL EXTRA EASY": 104, "INSTALL EASY": 106, "INSTALL MEDIUM": 108, "INSTALL HARD": 110,
    "INSTALL EXTRA HARD": 112, "INSTALL 3-BALL": 114, "INSTALL 5-BALL": 116, "INSTALL COMPETITION": 118,
    "INSTALL DIRECTOR'S CUT": 120, "INSTALL HOME PLAY": 122, "INSTALL NOVELTY": 124, "INSTALL ADD-A-BALL": 126,
    "INSTALL FACTORY": 128,
    "RESET COIN AUDITS": 130, "RESET GAME AUDITS": 132, "RESET GRAND CHAMPION": 134, "RESET HIGH SCORES": 136,
    "RESET CREDITS": 138, "RESET FACTORY SETTINGS": 140,
    "UPDATE GAME CODE": 142, "BACKUP TO USB MEMORY STICK": 144,
    "START TOURNAMENT": 146, "STOP TOURNAMENT": 148, "VIEW TOURNAMENT DATA": 150, "SIGN MESSAGES A-B": 152,
    "INSTALL REDEMPTION SYSTEM": 154, "CHANGE REDEMPTION SETTINGS": 156, "UNINSTALL REDEMPTION SYSTEM": 158,
    "VIEW REDEMPTION DATA": 160,
    "GAME-SPECIFIC TESTS": 1429, "3-BANK MOTOR TEST": 1431, "DISC MOTOR TEST": 1433,
    "RECOGNIZER MOTOR TEST": 1435, "FIBER OPTIC LIGHT TUBE TEST": 1437,
}
KIND_ICONS = {"back": 14, "exit": 16, "help": 18}     # PREV, QUIT, HELP


def item_icon(item):
    """The selected-state ROM image of a menu item (the dimmed one is the next image)."""
    return KIND_ICONS.get(item["kind"], ICONS.get(item["text"], 18))


def menu_draw(icons, sel, text):
    """FUN_01037588: the icon row of a menu, the selected item's text below it."""
    n = len(icons)
    total = n * ICON_W + n - 1
    out = []
    if total <= rd.WIDTH:
        x = (rd.WIDTH - total) // 2
        for i, icon in enumerate(icons):
            out.append(rd.image(icon if i == sel else icon + 1, x, 1))
            x += ICON_W + 1
    else:
        fit = (rd.WIDTH + 1) // (ICON_W + 1)           # icons that would fit: 7
        half, shown = (fit - 3) // 2, fit - 2
        rest = n - shown
        start = 0
        if half < sel:
            out.append(rd.image(MORE_LEFT, 1, 1))
            start = sel - half if sel < rest + half else rest
        x = ICON_W + 2
        for i in range(start, min(n, start + shown)):
            out.append(rd.image(icons[i] if i == sel else icons[i] + 1, x, 1))
            x += ICON_W + 1
        if sel < rest + half:
            out.append(rd.image(MORE_RIGHT, x, 1))
    out.append(rd.text(text, 2, 64, 30))
    return out


def screen_draw(lines):
    """The common layout of the ROM's test, audit and adjustment screens (FUN_0103e690, FUN_0103f040, ...):
    title in font 2 on row 5, the name in font 6 on row 14, the value in font 8 on row 22 and a last line
    in font 2 on row 30, each centred (a smaller font when the text is too wide)."""
    rows = ((5, (2, 0)), (14, (6, 2, 0)), (22, (8, 2, 0)), (30, SMALL_FONTS))
    return [rd.fit(t, 64, y, fonts) for t, (y, fonts) in zip(lines, rows) if t]


def header(title):
    """The utility screens' top (SET DATE/TIME, SET CUSTOM MESSAGE, CUSTOM PRICING, the tube test ...): the
    title in font 2 on row 4 over a rule on row 6 at level 3 (dmd_hline(0, 6, 128, 3))."""
    return [rd.text(title, 2, 64, 4), rd.box(0, 6, rd.WIDTH, 1, 3)]


def done_draw(first, second):
    """The confirmation of a reset, install or set [FUN_01022acc ...]: the subject fitted on row 10, the
    result in font 8 on row 18, PRESS 'SELECT' TO CONTINUE fitted on row 27."""
    return [rd.fit(first, 64, 10, TITLE_FONTS), rd.text(second, 8, 64, 18), rd.fit(CONTINUE, 64, 27, SMALL_FONTS)]


_LABELS = {}


def rom_label(device):
    """A switch, coil or lamp's ROM name (the comments of the package's config files), else its MPF name."""
    if not _LABELS:
        from tron.settings import ROOT
        for kind in ("switches", "coils", "lights"):
            path = os.path.join(ROOT, "assets", "mpf_package", "config", kind + ".yaml")
            if not os.path.exists(path):
                continue
            name = None
            with open(path, encoding="utf-8") as f:
                for line in f:
                    m = re.match(r"^  (\w+):\s*$", line)
                    if m:
                        name = m.group(1)
                        continue
                    m = re.match(r"^    number: \S+\s+#\s*(.+?)\s*$", line)
                    if m and name:
                        _LABELS[name] = m.group(1).upper()
    return _LABELS.get(device.name, device.name[2:].replace("_", " ").upper())


def hw_number(device):
    """Sort key: the device's SAM number (dedicated "D" numbers after the matrix)."""
    number = sam_number(device)
    return (1, int(number[1:])) if number[1:].isdigit() and number[0] == "D" else (
        (0, int(number)) if number.isdigit() else (2, 0))


def persist_var(machine, name, value):
    """A machine var saved to MPF's machine_vars data file."""
    machine.variables.configure_machine_var(name, persist=True)
    machine.variables.set_machine_var(name, value)


def menu_numbers():
    """{menu number: menu name}: the json lists the menus in the ROM's number order, MAIN MENU = 1."""
    return {i + 1: name for i, name in enumerate(service_data()["menus"])}


class Screen:
    """One service screen. button(name) handles a button, lines() returns the text (up to 3 lines)."""

    def __init__(self, svc, title):
        self.svc = svc
        self.os = svc.os
        self.machine = svc.machine
        self.title = title

    def enter(self):
        pass

    def leave(self):
        pass

    def button(self, name):
        if name == "back":
            self.svc.pop()

    def refresh(self):
        self.svc.render()

    def draw(self):
        """The DMD: a list of tron/rom_draw.py items (default: the common screen layout of the lines)."""
        return screen_draw(self.lines())


class EntryScreen(Screen):
    """The service entry screen, deff 3 [0x01037a6c]: version, SERVICE MENU, PRESS 'SELECT' TO CONTINUE.
    SELECT opens the main menu, BACK leaves; MINUS / PLUS show the technician alerts."""

    def __init__(self, svc):
        super().__init__(svc, "SERVICE MENU")

    def lines(self):
        return [self.title, CONTINUE, " ".join(VERSION)]

    def draw(self):
        game, version, system, hardware = VERSION
        return [rd.text(game, 2, 64, 5), rd.text(version, 2, 0, 11, 1), rd.text(system, 2, 64, 11),
                rd.text(hardware, 2, 127, 11, 4), rd.fit(self.title, 64, 23, TITLE_FONTS),
                rd.fit(CONTINUE, 64, 30, SMALL_FONTS)]

    def button(self, name):
        if name == "select":
            self.svc.push(MenuScreen(self.svc, "MAIN MENU"))
        elif name in ("minus", "plus"):
            self.svc.push(SwitchAlertsScreen(self.svc, "TECHNICIAN ALERTS"))
        else:
            self.svc.exit()


class MenuScreen(Screen):
    """A ROM menu: MINUS / PLUS move through the visible items, SELECT opens one, BACK goes up."""

    def __init__(self, svc, name):
        super().__init__(svc, name)
        self.pos = 0

    def items(self):
        items = [i for i in service_data()["menus"][self.title] if self.svc.visible(i)]
        # the game adds its items (GAME-SPECIFIC TESTS) at run time: the tail items stay last
        tail = [i for i in items if i["kind"] in ("back", "exit", "help")]
        return [i for i in items if i not in tail] + tail

    def lines(self):
        items = self.items()
        self.pos %= len(items)
        return [self.title, items[self.pos]["text"], "{} OF {}".format(self.pos + 1, len(items))]

    def draw(self):
        items = self.items()
        self.pos %= len(items)
        return menu_draw([item_icon(i) for i in items], self.pos, items[self.pos]["text"])

    def button(self, name):
        items = self.items()
        if name == "back":
            if self.title == "MAIN MENU":        # BACK in the main menu leaves the service menu [0x01037f04]
                self.svc.exit()
            else:
                self.svc.pop()
        elif name in ("minus", "plus"):
            self.pos = (self.pos + (1 if name == "plus" else -1)) % len(items)
            self.refresh()
        elif name == "select":
            self.svc.open_item(items[self.pos % len(items)])


class MessageScreen(Screen):
    def __init__(self, svc, title, *text):
        super().__init__(svc, title)
        self.text = list(text)

    def lines(self):
        return [self.title] + self.text


class HelpScreen(MessageScreen):
    def __init__(self, svc):
        super().__init__(svc, "HELP", "SELECT=ENTER  BACK=EXIT", "MINUS/PLUS=MOVE/CHANGE")


class ListScreen(Screen):
    """MINUS / PLUS scroll a list of entries; subclasses define entries() and entry_lines()."""

    def __init__(self, svc, title):
        super().__init__(svc, title)
        self.pos = 0

    def current(self):
        entries = self.entries()
        if not entries:
            return None
        self.pos %= len(entries)
        return entries[self.pos]

    def lines(self):
        entry = self.current()
        return [self.title] + (self.entry_lines(entry) if entry is not None else ["NONE"])

    def move(self, step):
        n = len(self.entries())
        if n:
            self.pos = (self.pos + step) % n
            self.moved()
        self.refresh()

    def moved(self):
        pass

    def button(self, name):
        if name == "minus":
            self.move(-1)
        elif name == "plus":
            self.move(1)
        else:
            super().button(name)


# ---------------------------------------------------------------------------------------------- switches

SW_LINE, SW_ROW, SW_CELL = 0xa4, 0xa7, 0xa5      # ROM images: 52 x 1 rule, 50 x 3 row of 16 cells, 3 x 3 dot
SW_ROWS = (4, 2)                                   # matrix switches 1-64, dedicated switches D1-D32
SW_TEXT_X = 50 + (128 - 50) // 2                   # the texts' centre right of the grid


def switch_cell(switch):
    """(block, index) of a switch in the switch test grid: matrix 1-64 in block 0, dedicated D<n> in block 1."""
    number = sam_number(switch)
    if number.isdigit() and 1 <= int(number) <= 64:
        return 0, int(number) - 1
    if number[:1] == "D" and number[1:].isdigit() and 1 <= int(number[1:]) <= 32:
        return 1, int(number[1:]) - 1
    return None


def switch_number_text(switch):
    """msg 0x113 / 0x114: a matrix switch's number, a dedicated one's (texts inferred: not in the package)."""
    cell = switch_cell(switch)
    if cell and cell[0] == 1:
        return "DEDICATED #{}".format(cell[1] + 1)
    return "SWITCH #{}".format(sam_number(switch) or "?")


def switch_grid(machine):
    """The switch matrix drawing of SWITCH TEST / ACTIVE SWITCH TEST [FUN_01044bfc, FUN_01043a74]: rules and
    rows of 16 cells, centred on the display's rows, a dot on every closed switch."""
    y = (32 - (3 * sum(SW_ROWS) + len(SW_ROWS) + 1)) // 2
    out = [rd.image(SW_LINE, 0, y)]
    y += 1
    tops = []
    for rows in SW_ROWS:
        tops.append(y)
        for _ in range(rows):
            out.append(rd.image(SW_ROW, 1, y))
            y += 3
        out.append(rd.image(SW_LINE, 0, y))
        y += 1
    sc = machine.switch_controller
    for switch in machine.switches.values():
        cell = switch_cell(switch)
        if cell and sc.is_active(switch):
            block, i = cell
            out.append(rd.image(SW_CELL, 2 + 3 * (i % 16), tops[block] + 3 * (i // 16)))
    return out


class SwitchTestScreen(Screen):
    """SWITCH TEST [FUN_01044bfc]: the switch grid, the last switch that closed, its name and number."""

    def __init__(self, svc):
        super().__init__(svc, "SWITCH TEST")
        self.last = None

    def enter(self):
        self.machine.switch_controller.add_monitor(self._changed)

    def leave(self):
        self.machine.switch_controller.remove_monitor(self._changed)

    def _changed(self, change):
        if change.name in BUTTONS:
            return
        if change.state:
            self.last = self.machine.switches[change.name]
        self.refresh()

    def lines(self):
        if not self.last:
            return [self.title, "NONE"]
        return [self.title, rom_label(self.last), switch_number_text(self.last)]

    def draw(self):
        lines = self.lines()
        out = switch_grid(self.machine) + [rd.fit(self.title, SW_TEXT_X, 8, SMALL_FONTS, width=76)]
        return out + [rd.fit(t, SW_TEXT_X, y, (0,), width=76) for t, y in zip(lines[1:], (15, 21))]


class ActiveSwitchScreen(ListScreen):
    """ACTIVE SWITCH TEST [FUN_01043a74]: the switch grid; MINUS / PLUS step through the closed switches."""

    def __init__(self, svc):
        super().__init__(svc, "ACTIVE SWITCHES")

    def entries(self):
        sc = self.machine.switch_controller
        return [s for s in sorted(self.machine.switches.values(), key=lambda s: hw_number(s))
                if sc.is_active(s) and s.name not in BUTTONS]

    def entry_lines(self, entry):
        return [rom_label(entry), switch_number_text(entry)]

    def draw(self):
        lines = self.lines()
        out = switch_grid(self.machine) + [rd.fit(self.title, SW_TEXT_X, 11, SMALL_FONTS, width=76)]
        return out + [rd.fit(t, SW_TEXT_X, y, (0,), width=76) for t, y in zip(lines[1:], (18, 24))]


class SwitchAlertsScreen(ListScreen):
    """SWITCH ALERTS / TECHNICIAN ALERTS: playfield switches never seen active since power-on."""

    def __init__(self, svc, title="SWITCH ALERTS"):
        super().__init__(svc, title)

    def entries(self):
        return [s for s in sorted(self.machine.switches.values(), key=lambda s: hw_number(s))
                if s.name.startswith("s_") and s.name not in BUTTONS and s.last_change < 0
                and not self.machine.switch_controller.is_active(s)]

    def lines(self):
        entries = self.entries()
        if not entries:
            return [self.title, "NO ALERTS"]
        return super().lines()

    def entry_lines(self, entry):
        return [rom_label(entry), "NOT ACTIVE", "{} OF {}".format(self.pos + 1, len(self.entries()))]

    def draw(self):
        """TECHNICIAN ALERTS [FUN_01040b94]: TECHNICIAN ALERT - (n/m) on row 4; NO / TECHNICIAN ALERTS in
        font 8 when there is none."""
        entries = self.entries()
        if not entries:
            return [rd.text(self.title, 2, 64, 4), rd.text("NO", 8, 64, 14), rd.text(self.title, 8, 64, 23)]
        entry = self.current()
        return [rd.text("TECHNICIAN ALERT - ({}/{})".format(self.pos + 1, len(entries)), 2, 64, 4),
                rd.fit(rom_label(entry), 64, 14, (6, 2, 0)), rd.text("NOT ACTIVE", 8, 64, 22)]


# ---------------------------------------------------------------------------------------------- coils, lamps

class CoilTestScreen(ListScreen):
    """SINGLE COIL / SINGLE FLASH LAMP TEST [FUN_0103f040, FUN_010413b0]: MINUS / PLUS pick, SELECT fires;
    the cycling variants [FUN_0103eb8c, FUN_01040edc] fire each output in turn, CYCLE_SECONDS apart. Screen:
    title, the output's name in font 6, its driver number "#n" in font 8."""

    def __init__(self, svc, title, coils, cycling=False):
        super().__init__(svc, title)
        self.coils = coils
        self.cycling = cycling
        self.handle = None
        self.fired = []

    def entries(self):
        return self.coils

    def entry_lines(self, entry):
        return [rom_label(entry), "#{}".format(sam_number(entry))]

    def enter(self):
        if self.cycling:
            self._cycle()

    def leave(self):
        if self.handle:
            self.machine.clock.unschedule(self.handle)
            self.handle = None

    def fire(self, coil):
        coil.pulse()
        self.fired.append(coil.name)

    def _cycle(self):
        self.fire(self.current())
        self.refresh()
        self.pos += 1
        self.handle = self.machine.clock.schedule_once(self._cycle, CYCLE_SECONDS)

    def button(self, name):
        if name == "select" and not self.cycling:
            self.fire(self.current())
        else:
            super().button(name)


LAMP_LINE, LAMP_CELL, LAMP_ROW = 0xaa, 0xab, 0xac   # ROM images: 28 x 1 rule, 3 x 3 dot, 26 x 3 row of 8 cells
LAMP_TEXT_X = 26 + (128 - 26) // 2


def lamp_grid(lights):
    """The lamp matrix drawing of the lamp tests [FUN_01041e08]: 10 rows of 8 cells between two rules, a dot
    on each lamp of `lights` (lamp n: row (n - 1) >> 3, cell (n - 1) & 7)."""
    out = [rd.image(LAMP_LINE, 0, 0)] + [rd.image(LAMP_ROW, 1, 1 + 3 * r) for r in range(10)]
    out.append(rd.image(LAMP_LINE, 0, 31))
    for light in lights:
        n = int(sam_number(light)) - 1
        out.append(rd.image(LAMP_CELL, 2 + 3 * (n & 7), 1 + 3 * (n >> 3)))
    return out


class LampTestScreen(ListScreen):
    """SINGLE LAMP TEST (one lamp), TEST ALL LAMPS, LAMP ROW / COLUMN TEST (one row or column of the SAM
    8 x 10 lamp matrix): the lamps blink at the service priority over everything else. Screen
    [FUN_010427dc, FUN_01041e08, FUN_01042fc0, FUN_010421e4]: the lamp grid with the lit lamps, the title
    and the lamp or group to its right."""

    TITLES = {"SINGLE LAMP TEST": "SINGLE LAMP TEST", "TEST ALL LAMPS": "ALL LAMPS TEST",
              "LAMP ROW TEST": "ROW LAMPS TEST", "LAMP COLUMN TEST": "COLUMN LAMPS TEST"}

    def __init__(self, svc, title, groups):
        super().__init__(svc, title)
        self.groups = groups          # [(label, [lights], lamp number text)]
        self.lit = []
        self.on = False
        self.handle = None

    def entries(self):
        return self.groups

    def entry_lines(self, entry):
        return [entry[0], entry[2] if len(entry) > 2 else "{} OF {}".format(self.pos + 1, len(self.groups))]

    def draw(self):
        entry = self.current()
        title = self.TITLES.get(self.title, self.title)
        out = lamp_grid(entry[1] if self.on else [])
        if self.title == "TEST ALL LAMPS":
            out.append(rd.text(title, 2, LAMP_TEXT_X, 11))
            if self.on:
                out.append(rd.text("ALL LAMPS ON", 8, LAMP_TEXT_X, 24))
            return out
        out.append(rd.fit(title, LAMP_TEXT_X, 8, SMALL_FONTS, width=100))
        lines = self.entry_lines(entry)
        return out + [rd.fit(t, LAMP_TEXT_X, y, (0,), width=100) for t, y in zip(lines, (15, 21))]

    def enter(self):
        self._blink()

    def moved(self):
        self._clear()

    def _clear(self):
        for light in self.lit:
            light.remove_from_stack_by_key(LOCK_KEY)
        self.lit = []

    def _blink(self):
        self.on = not self.on
        self._clear()
        if self.on:
            for light in self.current()[1]:
                light.color("white", key=LOCK_KEY, priority=LIGHT_PRIORITY)
                self.lit.append(light)
        self.handle = self.machine.clock.schedule_once(self._blink, BLINK_SECONDS)
        self.refresh()

    def leave(self):
        if self.handle:
            self.machine.clock.unschedule(self.handle)
            self.handle = None
        self._clear()


TROUGH_FLOOR, SHOOTER, BALL = 0xb0, 0xaf, 0xad    # ROM images: 111 x 8 trough floor, 17 x 32 shooter, 15 x 15 ball


class TroughTestScreen(Screen):
    """BALL TROUGH TEST [FUN_010383cc]: TROUGH TEST in font 0 at the top left over a rule on row 6, the trough
    floor and the shooter images, a ball with its switch number on each trough switch that is closed (the
    ROM's ball positions are a table not in the package: placed here on the floor's steps). SELECT ejects
    one ball to the shooter lane."""

    NAMES = ("s_trough_1_r", "s_trough_2", "s_trough_3", "s_trough_4_l")

    def __init__(self, svc):
        super().__init__(svc, "BALL TROUGH TEST")

    def lines(self):
        sc = self.machine.switch_controller
        states = " ".join("X" if sc.is_active(self.machine.switches[n]) else "-" for n in self.NAMES)
        return [self.title, "TROUGH 1-4: " + states, "SELECT=EJECT"]

    def draw(self):
        sc = self.machine.switch_controller
        out = [rd.text("TROUGH TEST", 0, 0, 4, 1), rd.box(0, 6, 128, 1, 3), rd.image(TROUGH_FLOOR, 0, 24),
               rd.image(SHOOTER, 111, 0)]
        for k, name in enumerate(self.NAMES):         # trough 1 (right) to 4 (left), on steps 5 to 2
            step = 5 - k
            x, y = 16 * step, 24 + step - 15
            switch = self.machine.switches[name]
            if sc.is_active(switch):
                out += [rd.image(BALL, x, y), rd.text(sam_number(switch), 0, x + 7, y + 9)]
        return out

    def button(self, name):
        if name == "select":
            self.machine.ball_devices["bd_trough"].eject()
            self.refresh()
        else:
            super().button(name)


class ActionScreen(Screen):
    """A screen where SELECT runs one action (knocker test, installs, resets, audit dump, backup): `before()`
    and `after()` return the ROM's draw lists before and after it; the lines are their texts."""

    def __init__(self, svc, title, action, before, after):
        super().__init__(svc, title)
        self.action, self.before, self.after = action, before, after
        self.done = False

    def draw(self):
        return self.after() if self.done else self.before()

    def lines(self):
        return rd.lines_of(self.draw())

    def button(self, name):
        if name == "select":
            if self.done and self.after is not knocker_draw_on:
                self.svc.pop()                   # PRESS 'SELECT' TO CONTINUE
                return
            self.action()
            self.done = True
            self.refresh()
        else:
            super().button(name)


def reset_draw(title):
    """A reset's question [FUN_01022acc and kin]: the reset fitted on row 10, then the two PRESS lines."""
    return [rd.fit(title, 64, 10, TITLE_FONTS), rd.text("PRESS 'SELECT' TO RESET", 2, 64, 21),
            rd.text(CANCEL, 2, 64, 27)]


RESET_DONE = {"RESET COIN AUDITS": ("RESET COIN AUDITS", "COMPLETE"),
              "RESET GAME AUDITS": ("RESET GAME AUDITS", "COMPLETE"),
              "RESET GRAND CHAMPION": ("GRAND CHAMPION SCORES", "RESET"),
              "RESET HIGH SCORES": ("HIGH SCORES", "RESET"),
              "RESET FACTORY SETTINGS": ("FACTORY RESET", "COMPLETE")}


def reset_credits_draw():
    return [rd.text("RESET CREDITS", 8, 64, 8), rd.text("PRESS 'SELECT' TO RESET", 2, 64, 23),
            rd.text(CANCEL, 2, 64, 29)]


def reset_credits_done():
    return [rd.text("RESET CREDITS COMPLETE", 2, 64, 8), rd.fit(CONTINUE, 64, 27, SMALL_FONTS)]


def install_draw(title, installed):
    """An install [FUN_01041a10]: the install fitted on row 9, (INSTALLED) when its settings are the
    current ones, PRESS 'SELECT' TO INSTALL and PRESS 'BACK' TO CANCEL in font 2."""
    out = [rd.fit(title, 64, 9, TITLE_FONTS)]
    if installed:
        out.append(rd.text("(INSTALLED)", 2, 64, 15))
    return out + [rd.text("PRESS 'SELECT' TO INSTALL", 2, 64, 22), rd.text(CANCEL, 2, 64, 28)]


def install_name(text):
    return "FACTORY SETTINGS" if text == "INSTALL FACTORY" else text[len("INSTALL "):]


def knocker_draw():
    """KNOCKER TEST [FUN_010386f4]: KNOCKER TEST in font 8, PRESS 'SELECT' TO ACTIVATE fitted on row 15 and
    KNOCKER in the same font on row 22; ACTIVATING KNOCKER on row 29 while it fires."""
    press = rd.fit("PRESS 'SELECT' TO ACTIVATE", 64, 15, SMALL_FONTS)
    return [rd.text("KNOCKER TEST", 8, 64, 8), press, rd.text("KNOCKER", press["f"], 64, 22)]


def knocker_draw_on():
    return knocker_draw() + [rd.text("ACTIVATING KNOCKER", 2, 64, 29)]


def usb_draw(title, press):
    """AUDIT DATA DUMP / GAME CODE BACKUP: the title on row 4, PRESS 'SELECT' ..., OR, PRESS 'BACK' TO EXIT."""
    return [rd.text(title, 2, 64, 4), rd.fit(press, 64, 19, SMALL_FONTS), rd.text("OR", 2, 64, 25),
            rd.text("PRESS 'BACK' TO EXIT", 2, 64, 31)]


def big_two(first, second):
    return [rd.text(first, 8, 64, 10), rd.text(second, 8, 64, 18)]


class SoundTestScreen(ListScreen):
    """SOUND/SPEAKER TEST: MINUS / PLUS pick a sound call, SELECT plays it."""

    def __init__(self, svc):
        super().__init__(svc, "SOUND/SPEAKER TEST")
        data = self.os.media.data
        self.calls = sorted(data["pools"]) if data else list(range(0x009, 0x1d0))
        self.played = []

    def entries(self):
        return self.calls

    def entry_lines(self, entry):
        return ["SOUND {:03X}".format(entry), "#{}".format(self.pos + 1)]

    def draw(self):
        """SOUND / SPEAKER TEST (msg 0x21f): the title on row 5, the sound's name in font 6 on row 14, its
        number "#n" in font 8 on row 22 (the ROM's sound names are not in the package: the call number)."""
        name, number = self.entry_lines(self.current())
        return [rd.text("SOUND / SPEAKER TEST", 2, 64, 5), rd.fit(name, 64, 14, (6, 2, 0)),
                rd.text(number, 8, 64, 22), rd.fit("PRESS 'SELECT' TO PLAY", 64, 30, SMALL_FONTS)]

    def button(self, name):
        if name == "select":
            self.os.sound(self.current())
            self.played.append(self.current())
        else:
            super().button(name)


class BurnInScreen(Screen):
    """BEGIN BURN-IN: SELECT starts lamp effect 8 and every coil in turn until BACK. Screen (msg
    0x23b-0x240): BURN-IN on row 4, TOTAL BURN-IN TIME: and the time m:ss in font 8 on rows 14 and 23,
    PRESS 'SELECT' TO START on row 31 until it runs."""

    def __init__(self, svc):
        super().__init__(svc, "BURN-IN")
        self.cycles = 0
        self.handle = None
        self.running = False
        self.coils = svc.coils(flashers=None)

    def start(self):
        self.running = True
        self.os.leff_start(8)
        self._step()

    def _step(self):
        coil = self.coils[self.cycles % len(self.coils)]
        coil.pulse()
        self.cycles += 1
        self.refresh()
        self.handle = self.machine.clock.schedule_once(self._step, CYCLE_SECONDS)

    def leave(self):
        if self.handle:
            self.machine.clock.unschedule(self.handle)
        if self.running:
            self.os.leff_stop(8)

    def elapsed(self):
        seconds = int(self.cycles * CYCLE_SECONDS)
        if seconds >= 3600:
            return "{}:{:02d}:{:02d}".format(seconds // 3600, seconds // 60 % 60, seconds % 60)
        return "{}:{:02d}".format(seconds // 60, seconds % 60)

    def lines(self):
        return [self.title, "TOTAL BURN-IN TIME:", self.elapsed()]

    def draw(self):
        out = [rd.text(self.title, 2, 64, 4), rd.text("TOTAL BURN-IN TIME:", 8, 64, 14),
               rd.text(self.elapsed(), 8, 64, 23)]
        if not self.running:
            out.append(rd.fit("PRESS 'SELECT' TO START", 64, 31, SMALL_FONTS))
        return out

    def button(self, name):
        if name == "select" and not self.running:
            self.start()
        else:
            super().button(name)


class DotMatrixScreen(ListScreen):
    """DOT MATRIX TEST: full, blank and striped pages; MINUS / PLUS step."""

    PAGES = (("ALL DOTS ON", "#" * 21), ("ALL DOTS OFF", ""), ("STRIPES", "# " * 10 + "#"))

    def __init__(self, svc):
        super().__init__(svc, "DOT MATRIX TEST")

    def entries(self):
        return list(self.PAGES)

    def entry_lines(self, entry):
        return [entry[0], entry[1]]

    def draw(self):
        """The page itself: every dot lit, none, or every other row lit (the ROM's pages are not in the
        decompile)."""
        name = self.current()[0]
        if name == "ALL DOTS ON":
            return [rd.box(0, 0, rd.WIDTH, 32, 15)]
        if name == "STRIPES":
            return [rd.box(0, y, rd.WIDTH, 1, 15) for y in range(0, 32, 2)]
        return []


class MotorTestScreen(Screen):
    """GAME-SPECIFIC TESTS: SELECT starts / stops a motor coil (and MINUS / PLUS the disc direction relay);
    the position switches are shown."""

    def __init__(self, svc, title, coils, switches, direction=None):
        super().__init__(svc, title)
        self.coils = [self.machine.coils[c] for c in coils]
        self.switches = switches
        self.direction = self.machine.coils[direction] if direction else None
        self.running = False
        self.reverse = False

    def lines(self):
        sc = self.machine.switch_controller
        sw = " ".join("{}:{}".format(n.upper()[2:].replace("_MOTOR", ""), "X" if sc.is_active(
            self.machine.switches[n]) else "-") for n in self.switches)
        state = ("RUNNING" if self.running else "STOPPED") + (" REVERSE" if self.reverse else "")
        return [self.title, state, sw]

    def draw(self):
        """RECOGNIZER MOTOR TEST [FUN_01022acc] and kin: the title on row 4, USE -/+ OR 'SELECT' TO TEST on
        row 30; the motor state and its position switches between them."""
        _, state, sw = self.lines()
        out = [rd.text(self.title, 2, 64, 4), rd.fit(state, 64, 14, (8, 2, 0))]
        if sw:
            out.append(rd.fit(sw, 64, 22, SMALL_FONTS))
        return out + [rd.text("USE -/+ OR 'SELECT' TO TEST", 2, 64, 30)]

    def _set(self, on):
        self.running = on
        for coil in self.coils:
            coil.enable() if on else coil.disable()

    def button(self, name):
        if name == "select":
            self._set(not self.running)
            self.refresh()
        elif name in ("minus", "plus") and self.direction:
            self.reverse = name == "minus"
            self.direction.enable() if self.reverse else self.direction.disable()
            self.refresh()
        else:
            super().button(name)

    def leave(self):
        self._set(False)
        if self.direction:
            self.direction.disable()


class TubeTestScreen(Screen):
    """FIBER OPTIC LIGHT TUBE TEST (ROM 0x1012b50): the two ramp tubes cycle through the attract colour
    shows (tube shows 2-9), one every second."""

    SHOWS = tuple(range(2, 10))

    def __init__(self, svc):
        super().__init__(svc, "FIBER OPTIC TUBE TEST")
        self.index = 0
        self.handle = None

    def enter(self):
        self._step()

    def _step(self):
        self.os.tube_stop(self.SHOWS[self.index % len(self.SHOWS)])
        self.index += 1
        self.os.tube_start(self.SHOWS[self.index % len(self.SHOWS)])
        self.refresh()
        self.handle = self.machine.clock.schedule_once(self._step, CYCLE_SECONDS)

    def leave(self):
        if self.handle:
            self.machine.clock.unschedule(self.handle)
        self.os.tube_stop(self.SHOWS[self.index % len(self.SHOWS)])

    def lines(self):
        return [self.title, "TUBE SHOW {}".format(self.SHOWS[self.index % len(self.SHOWS)])]

    def draw(self):
        """FUN_01012b50: the title over the rule, L. RAMP: and R. RAMP: on rows 14 and 22 with their R: G: B:
        levels (columns at x 40, 70, 100, values right-aligned at x 64, 94, 124), USE -/+ OR 'SELECT' TO
        TEST on row 30."""
        out = header("FIBER OPTIC TUBE TEST")
        for name, light, y in (("L. RAMP:", "l_left_ramp_tube", 14), ("R. RAMP:", "l_right_ramp_tube", 22)):
            out.append(rd.text(name, 2, 0, y, 1))
            device = self.machine.lights.get(light) if hasattr(self.machine, "lights") else None
            color = device.get_color() if device is not None else None
            levels = (color.red, color.green, color.blue) if color is not None else (0, 0, 0)
            for label, x, right, level in zip(("R:", "G:", "B:"), (40, 70, 100), (64, 94, 124), levels):
                out += [rd.text(label, 2, x, y, 1), rd.text(str(level), 2, right, y, 4)]
        return out + [rd.text("USE -/+ OR 'SELECT' TO TEST", 2, 64, 30)]


# ---------------------------------------------------------------------------------------------- audits

class AuditScreen(ListScreen):
    """EARNINGS / STANDARD / FEATURE AUDITS: one audit per page, number, ROM name and value."""

    def __init__(self, svc, title, group):
        super().__init__(svc, title)
        self.numbers = self.os.audits.menu(group)

    def entries(self):
        return self.numbers

    def entry_lines(self, number):
        audits = self.os.audits
        return ["{:02d} {}".format(number, audits.info[number]["name"]), audits.text(number)]

    def draw(self):
        """FUN_0103e690: the menu's title with the audit's number (message 0x154 and kin, text not in the
        package: "<MENU> #n") in font 2 on row 5, the audit's name in font 6 on row 14, its value in font 8 on
        row 22 (the [LIFETIME: ...] line of row 30 is not kept: no lifetime totals here)."""
        number = self.current()
        if number is None:
            return screen_draw([self.title, "NONE"])
        audits = self.os.audits
        return [rd.fit("{} #{}".format(self.title, number), 64, 5, SMALL_FONTS),
                rd.fit(audits.info[number]["name"], 64, 14, (6, 2, 0)), rd.fit(audits.text(number), 64, 22, (8, 2, 0))]


def dump_audits(os_, path):
    """DUMP AUDITS TO USB: every audit as "number name value" lines (the USB stick is the data folder)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for number in sorted(os_.audits.info):
            f.write("{:3d} {:34s} {}\n".format(number, os_.audits.info[number]["name"], os_.audits.text(number)))
    return path


# ---------------------------------------------------------------------------------------------- adjustments

class AdjustmentScreen(ListScreen):
    """STANDARD / FEATURE ADJUSTMENTS: MINUS / PLUS scroll; SELECT edits, MINUS / PLUS change the value by
    the ROM step, SELECT stores it (MPF setting, persisted), BACK drops the change."""

    def __init__(self, svc, title, group):
        super().__init__(svc, title)
        self.numbers = self.os.adj.menu(group)
        self.editing = None
        self.blink_on = True
        self.handle = None

    def entries(self):
        return self.numbers

    def entry_lines(self, num):
        adj = self.os.adj
        value = adj[num] if self.editing is None else self.editing
        mark = " (FACTORY)" if value == adj.default(num) else ""
        edit = "> " if self.editing is not None else ""      # the value being edited
        return ["{:02d} {}".format(num, adj.info[num]["name"]), edit + adj.label(num, value) + mark]

    def draw(self):
        """FUN_0103dd00: the menu's title with the adjustment's number in font 2 on row 5, the name in font 6
        on row 14, the value in font 8 on row 22 (blinking while it is edited) and on row 29, fitted,
        (INSTALLED, FACTORY DEFAULT) / (INSTALLED) for the stored value, (FACTORY DEFAULT) for the default."""
        num = self.current()
        adj = self.os.adj
        value = adj[num] if self.editing is None else self.editing
        out = [rd.fit("{} #{}".format(self.title, num), 64, 5, SMALL_FONTS),
               rd.fit(adj.info[num]["name"], 64, 14, (6, 2, 0))]
        if self.editing is None or self.blink_on:
            out.append(rd.fit(adj.label(num, value), 64, 22, (8, 2, 0)))
        notes = (["INSTALLED"] if value == adj[num] else []) + (
            ["FACTORY DEFAULT"] if value == adj.default(num) else [])
        if notes:
            out.append(rd.fit("({})".format(", ".join(notes)), 64, 29, SMALL_FONTS))
        return out

    def _blink(self):
        self.blink_on = not self.blink_on
        self.handle = self.machine.clock.schedule_once(self._blink, BLINK_SECONDS / 2)
        self.refresh()

    def _stop_blink(self):
        if self.handle:
            self.machine.clock.unschedule(self.handle)
            self.handle = None
        self.blink_on = True

    def leave(self):
        self._stop_blink()

    def button(self, name):
        num = self.current()
        if self.editing is None:
            if name == "select":
                self.editing = self.os.adj[num]
                self.handle = self.machine.clock.schedule_once(self._blink, BLINK_SECONDS / 2)
                self.refresh()
            else:
                super().button(name)
            return
        if name in ("minus", "plus"):
            self.editing = self.os.adj.step(num, self.editing, 1 if name == "plus" else -1)
        elif name == "select":
            self.os.adj[num] = self.editing
            self.editing = None
            self._stop_blink()
        elif name == "back":
            self.editing = None
            self._stop_blink()
        self.refresh()


# ---------------------------------------------------------------------------------------------- utilities

class CustomMessageScreen(Screen):
    """ENTER CUSTOM MESSAGE: MINUS / PLUS change the letter, SELECT goes to the next one and stores the
    message after the last (machine var custom_message_text, persisted); BACK leaves without storing."""

    def __init__(self, svc):
        super().__init__(svc, "ENTER CUSTOM MESSAGE")
        old = self.machine.variables.get_machine_var("custom_message_text") or ""
        self.text = list(old.ljust(CUSTOM_MESSAGE_LEN)[:CUSTOM_MESSAGE_LEN])
        self.cursor = 0

    def lines(self):
        marker = " " * self.cursor + "^"
        return [self.title, "".join(self.text), marker]

    def draw(self):
        """SET CUSTOM MESSAGE (msg 0x213): the header, the message in font 2 on row 18 left to right from
        x 16 by 6 dots (an editor of the ROM's own is not in the decompile), the letter edited underlined."""
        out = header("SET CUSTOM MESSAGE")
        for i, ch in enumerate(self.text):
            if ch != " ":
                out.append(rd.text(ch, 2, 16 + 6 * i + 2, 18))
        return out + [rd.box(16 + 6 * self.cursor, 20, 5, 1, 15)]

    def button(self, name):
        if name in ("minus", "plus"):
            ch = self.text[self.cursor]
            i = CHARSET.index(ch) if ch in CHARSET else 0
            self.text[self.cursor] = CHARSET[(i + (1 if name == "plus" else -1)) % len(CHARSET)]
        elif name == "select":
            self.cursor += 1
            if self.cursor >= CUSTOM_MESSAGE_LEN:
                persist_var(self.machine, "custom_message_text", "".join(self.text).rstrip())
                self.svc.pop()
                return
        else:
            super().button(name)
            return
        self.refresh()


class CustomPricingScreen(Screen):
    """SET CUSTOM PRICING: the CUSTOM pricing (adj 28 = 64, tron/credits.py) as coin units of the coin slot and
    units per credit (machine vars custom_coin_units, custom_units_per_credit, persisted). SELECT steps to the
    next value and stores both after the last one and sets adj 28 to CUSTOM; MINUS / PLUS change the value.
    The ROM's own editor is not in the decompile."""

    FIELDS = (("COIN UNITS", "custom_coin_units", 1), ("UNITS PER CREDIT", "custom_units_per_credit", 3))

    def __init__(self, svc):
        super().__init__(svc, "SET CUSTOM PRICING")
        var = self.machine.variables.get_machine_var
        self.values = [int(var(key) or default) for _, key, default in self.FIELDS]
        self.field = 0

    def lines(self):
        return [self.title, self.FIELDS[self.field][0], "> {}".format(self.values[self.field])]

    def draw(self):
        """CUSTOM PRICING (msg 0x4c1): the header, the field edited in font 2 on row 14 and its value in font 8
        on row 25."""
        return header("CUSTOM PRICING") + [rd.text(self.FIELDS[self.field][0], 2, 64, 14),
                                           rd.text(str(self.values[self.field]), 8, 64, 25)]

    def button(self, name):
        if name in ("minus", "plus"):
            v = self.values[self.field] + (1 if name == "plus" else -1)
            self.values[self.field] = min(CUSTOM_PRICING_MAX, max(1, v))
        elif name == "select":
            self.field += 1
            if self.field == len(self.FIELDS):
                for (_, key, _), value in zip(self.FIELDS, self.values):
                    persist_var(self.machine, key, value)
                self.os.adj[28] = 64
                self.svc.pop()
                return
        else:
            super().button(name)
            return
        self.refresh()


def clock_now(machine):
    """The game clock: the host clock plus the operator's SET DATE/TIME offset (machine var clock_offset)."""
    offset = machine.variables.get_machine_var("clock_offset") or 0
    return datetime.datetime.now() + datetime.timedelta(seconds=offset)


def clock_text(machine, when, time_format):
    """Date and time as the ROM shows them: adj 3 TIME FORMAT 0 = 12-HOUR, 1 = 24-HOUR."""
    if time_format == 1:
        clock = when.strftime("%H:%M")
    else:
        clock = "{}:{:02d} {}".format(when.hour % 12 or 12, when.minute, "PM" if when.hour >= 12 else "AM")
    return when.strftime("%Y-%m-%d"), clock


class DateTimeScreen(Screen):
    """SET DATE/TIME: SELECT steps through year, month, day, hour, minute (MINUS / PLUS change the field)
    and stores the clock offset after the minutes."""

    FIELDS = ("YEAR", "MONTH", "DAY", "HOUR", "MINUTE")

    def __init__(self, svc):
        super().__init__(svc, "SET DATE/TIME")
        self.when = clock_now(self.machine).replace(second=0, microsecond=0)
        self.field = 0

    def lines(self):
        date, clock = clock_text(self.machine, self.when, self.os.adj[3])
        return ["SET " + self.FIELDS[self.field], date, clock]

    def draw(self):
        """SET DATE/TIME (msg 0x1e6): the header, the field edited (CURRENT DATE/TIME: in the ROM) on row 16,
        the date and the time in font 2 on rows 23 and 30."""
        title, date, clock = self.lines()
        return header("SET DATE/TIME") + [rd.text(title, 2, 64, 16), rd.text(date, 2, 64, 23),
                                          rd.text(clock, 2, 64, 30)]

    def _change(self, step):
        w = self.when
        field = self.FIELDS[self.field]
        if field == "YEAR":
            w = w.replace(year=min(2099, max(2000, w.year + step)))
        elif field == "MONTH":
            w = w.replace(month=(w.month - 1 + step) % 12 + 1, day=min(w.day, 28))
        elif field == "DAY":
            w = w + datetime.timedelta(days=step)
        elif field == "HOUR":
            w = w + datetime.timedelta(hours=step)
        else:
            w = w + datetime.timedelta(minutes=step)
        self.when = w

    def button(self, name):
        if name in ("minus", "plus"):
            self._change(1 if name == "plus" else -1)
        elif name == "select":
            self.field += 1
            if self.field == len(self.FIELDS):
                offset = int((self.when - datetime.datetime.now()).total_seconds())
                persist_var(self.machine, "clock_offset", offset)
                self.svc.pop()
                return
        else:
            super().button(name)
            return
        self.refresh()


# ---------------------------------------------------------------------------------------------- the mode

class ServiceMode(Mode):
    """MPF mode tron_service: the menu stack, the coin-door buttons and the display."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.stack = []
        self.handlers = []
        self.lines = []
        self.draw_items = []
        self.dump_path = os.path.join(self.machine.machine_path, "data", "audit_dump.txt")

    @property
    def os(self):
        return self.machine.tron

    def mode_start(self, **kwargs):
        os_ = self.os
        os_.in_service = True
        attract = os_.features_by_name.get("attract")
        if attract:
            attract.stop()                        # the ROM's attract pages and lamp show stop
        os_.deff_stop(1)
        os_.leff_stop(1)
        if self.machine.modes["attract"].active:
            self.machine.modes["attract"].stop()  # no game start from the service menu
        sc = self.machine.switch_controller
        for name, button in BUTTONS.items():
            self.handlers.append(sc.add_switch_handler(name, self._button, callback_kwargs={"name": button}))
        self.stack = []
        self.push(EntryScreen(self))
        self.machine.events.post("tron_service_entered")

    def mode_stop(self, **kwargs):
        while self.stack:
            self.stack.pop().leave()
        for handler in self.handlers:
            self.machine.switch_controller.remove_switch_handler_by_key(handler)
        self.handlers = []
        os_ = self.os
        os_.in_service = False
        os_.media.service_hide()
        self.machine.events.post("tron_service_exited")
        if not self.machine.modes["attract"].active:
            self.machine.modes["attract"].start()
        os_.hook("attract_start")                 # event 0x08: attract pages and lamp show again

    # ------------------------------------------------------------------ navigation

    def _button(self, name):
        if self.stack:
            self.stack[-1].button(name)

    def push(self, screen):
        self.stack.append(screen)
        screen.enter()
        self.render()

    def pop(self):
        self.stack.pop().leave()
        if not self.stack:
            self.stop()
            return
        self.render()

    def exit(self):
        self.stop()

    def render(self):
        screen = self.stack[-1]
        lines = (screen.lines() + ["", "", ""])[:3]
        self.lines = lines
        self.draw_items = screen.draw()
        self.os.media.service_show(lines, self.draw_items)
        self.machine.events.post("tron_service_display", line0=lines[0], line1=lines[1], line2=lines[2])

    def visible(self, item):
        """The ROM's shown_only_if conditions for the menu items."""
        cond = item.get("shown_only_if")
        if not cond:
            return True
        adj = self.os.adj
        redemption = adj[45] != 0                 # a ticket dispenser is configured
        return {
            "0x2ffc0": False,                     # tournament mode available: no tournament system here
            "0x30078": False, "0x3005c": False, "0x30034": False,
            "0x101298c": redemption,
            "0x30004": redemption, "0x2ffec": redemption, "0x2ffd4": redemption, "0x3001c": redemption,
            "0x32e7c": False,                     # DISPLAY SOFTWARE ERRORS: no errors logged
        }.get(cond, False)

    def open_item(self, item):
        kind, text = item["kind"], item["text"]
        if kind == "submenu":
            self.push(MenuScreen(self, menu_numbers()[item["submenu"]]))
        elif kind == "back":
            self.pop()
        elif kind == "exit":
            self.exit()
        elif kind == "help":
            self.push(HelpScreen(self))
        else:
            self.push(self.screen_for(text))

    # ------------------------------------------------------------------ hardware lists

    def coils(self, flashers=False):
        """The ROM's coils (flashers=False), flash lamps (True) or both (None), by driver number."""
        flash = set(flasher_names())
        coils = [c for c in self.machine.coils.values()
                 if flashers is None or (c.name in flash) == bool(flashers)]
        return sorted(coils, key=lambda c: hw_number(c))

    def lamp_groups(self, how):
        lights = sorted((light for light in self.machine.lights.values() if sam_number(light).isdigit()
                         and not light.config.get("platform")), key=lambda light: int(sam_number(light)))
        if how == "single":
            return [(rom_label(lt), [lt], "LAMP #{}".format(sam_number(lt))) for lt in lights]
        if how == "all":
            return [("ALL LAMPS", lights, "")]
        groups = {}
        for light in lights:
            n = int(sam_number(light)) - 1
            key = n // 8 + 1 if how == "column" else n % 8 + 1
            groups.setdefault(key, []).append(light)
        return [("{} {}".format(how.upper(), k), v, "{} OF {}".format(i + 1, len(groups)))
                for i, (k, v) in enumerate(sorted(groups.items()))]

    # ------------------------------------------------------------------ screens by item text

    def screen_for(self, text):
        os_ = self.os
        adj, audits = os_.adj, os_.audits
        if text.startswith("INSTALL ") and text in service_data()["install_presets"] or text == "INSTALL FACTORY":
            return ActionScreen(self, text, lambda: adj.install(text),
                                lambda: install_draw(text, self.installed(text)),
                                lambda: done_draw(install_name(text), "INSTALLED"))
        resets = {
            "RESET COIN AUDITS": audits.reset_coin,
            "RESET GAME AUDITS": audits.reset_game,
            "RESET GRAND CHAMPION": lambda: self.reset_high_scores(1),
            "RESET HIGH SCORES": lambda: self.reset_high_scores(2),
            "RESET CREDITS": self.reset_credits,
            "RESET FACTORY SETTINGS": self.factory_reset,
        }
        if text == "RESET CREDITS":
            return ActionScreen(self, text, resets[text], reset_credits_draw, reset_credits_done)
        if text in resets:
            return ActionScreen(self, text, resets[text], lambda: reset_draw(text),
                                lambda: done_draw(*RESET_DONE[text]))
        screens = {
            "SWITCH TEST": lambda: SwitchTestScreen(self),
            "ACTIVE SWITCH TEST": lambda: ActiveSwitchScreen(self),
            "SWITCH ALERTS": lambda: SwitchAlertsScreen(self),
            "TECHNICIAN ALERTS": lambda: SwitchAlertsScreen(self, "TECHNICIAN ALERTS"),
            "SINGLE COIL TEST": lambda: CoilTestScreen(self, text, self.coils()),
            "CYCLING COIL TEST": lambda: CoilTestScreen(self, text, self.coils(), cycling=True),
            "SINGLE FLASH LAMP TEST": lambda: CoilTestScreen(self, text, self.coils(True)),
            "CYCLING FLASH LAMP TEST": lambda: CoilTestScreen(self, text, self.coils(True), cycling=True),
            "SINGLE LAMP TEST": lambda: LampTestScreen(self, text, self.lamp_groups("single")),
            "TEST ALL LAMPS": lambda: LampTestScreen(self, text, self.lamp_groups("all")),
            "LAMP ROW TEST": lambda: LampTestScreen(self, text, self.lamp_groups("row")),
            "LAMP COLUMN TEST": lambda: LampTestScreen(self, text, self.lamp_groups("column")),
            "BALL TROUGH TEST": lambda: TroughTestScreen(self),
            "KNOCKER TEST": lambda: ActionScreen(self, text, lambda: os_.knock(forced=True), knocker_draw,
                                                 knocker_draw_on),
            "SOUND/SPEAKER TEST": lambda: SoundTestScreen(self),
            "BEGIN BURN-IN": lambda: BurnInScreen(self),
            "DOT MATRIX TEST": lambda: DotMatrixScreen(self),
            "3-BANK MOTOR TEST": lambda: MotorTestScreen(self, text, ["c_recognizer_3_bank_motor_relay"],
                                                         ["s_3_bank_motor_up", "s_3_bank_motor_dn"]),
            "DISC MOTOR TEST": lambda: MotorTestScreen(self, text, ["c_disc_motor_power", "c_disc_motor_relay"],
                                                       [], direction="c_disc_direction_relay"),
            "RECOGNIZER MOTOR TEST": lambda: MotorTestScreen(
                self, text, ["c_recognizer_motor_relay"],
                ["s_recog_motor_pos_1", "s_recog_motor_pos_2", "s_recog_motor_pos_3"]),
            "FIBER OPTIC LIGHT TUBE TEST": lambda: TubeTestScreen(self),
            "EARNINGS AUDITS": lambda: AuditScreen(self, text, "earnings"),
            "STANDARD AUDITS": lambda: AuditScreen(self, text, "standard"),
            "FEATURE AUDITS": lambda: AuditScreen(self, text, "feature"),
            "DUMP AUDITS TO USB": lambda: ActionScreen(
                self, text, lambda: dump_audits(os_, self.dump_path),
                lambda: usb_draw("AUDIT DATA DUMP", "PRESS 'SELECT' TO SAVE AUDITS"),
                lambda: big_two("AUDIT DUMP", "COMPLETE") + [rd.fit(CONTINUE, 64, 27, SMALL_FONTS)]),
            "STANDARD ADJUSTMENTS": lambda: AdjustmentScreen(self, text, "standard"),
            "FEATURE ADJUSTMENTS": lambda: AdjustmentScreen(self, text, "feature"),
            "ENTER CUSTOM MESSAGE": lambda: CustomMessageScreen(self),
            "SET DATE/TIME": lambda: DateTimeScreen(self),
            "SET CUSTOM PRICING": lambda: CustomPricingScreen(self),
            "UPDATE GAME CODE": lambda: MessageScreen(self, "GAME CODE UPDATE", "NO UPDATE FOUND"),
            "BACKUP TO USB MEMORY STICK": lambda: ActionScreen(
                self, text, lambda: dump_audits(os_, self.dump_path),
                lambda: usb_draw("GAME CODE BACKUP", "PRESS 'SELECT' TO SAVE IMAGE"),
                lambda: big_two("GAME CODE IMAGE", "SAVED") + [rd.fit(CONTINUE, 64, 27, SMALL_FONTS)]),
        }
        return screens.get(text, lambda: MessageScreen(self, text, "NOT AVAILABLE"))()

    def installed(self, text):
        """(INSTALLED) of an install: its adjustments are the current values (FUN_00001118); the difficulty
        presets of 1.74 list none."""
        adj = self.os.adj
        if text == "INSTALL FACTORY":
            return all(adj[n] == adj.default(n) for n in adj.keys())
        entries = service_data()["install_presets"].get(text, [])
        return bool(entries) and all(adj[e["adj"]] == e["value"] for e in entries)

    # ------------------------------------------------------------------ resets

    def reset_credits(self):
        self.os.credit_model.reset()

    def reset_high_scores(self, mask):
        """RESET GRAND CHAMPION (1) / RESET HIGH SCORES (2) [0x0001a9f4]; 3 = both and the reset counter."""
        hs = self.os.features_by_name.get("high_scores")
        if hs:
            hs.reset_all() if mask == 3 else hs.reset(mask)

    def factory_reset(self):
        """RESET FACTORY SETTINGS: adjustments to their defaults, audits cleared, high scores and credits."""
        self.os.adj.factory_reset()
        self.os.audits.reset_all()
        self.reset_high_scores(3)
        self.reset_credits()


_FLASHERS = None


def flasher_names():
    """The outputs listed under "flashers:" in the package's coils.yaml (MPF 0.80 has them as coils)."""
    global _FLASHERS
    if _FLASHERS is None:
        from tron.settings import ROOT
        names, inside = [], False
        with open(os.path.join(ROOT, "assets", "mpf_package", "config", "coils.yaml"), encoding="utf-8") as f:
            for line in f:
                if line.strip() and not line.startswith((" ", "#")):
                    inside = line.startswith("flashers:")
                elif inside and line.startswith("  ") and not line.startswith("   ") and line.strip().endswith(":"):
                    names.append(line.strip()[:-1])
        _FLASHERS = names
    return _FLASHERS
