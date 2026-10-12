"""The service menu (tron/service.py): the ROM menu tree from service_menu.json, every screen it opens, the
hardware tests, audits display and resets, adjustment editing, install presets, date and time, and the
persistence of settings and audits across a power cycle (MPF data files)."""
import os
import tempfile
from unittest import mock

from tests.tron_test import GAME, TronTestCase

import sys
if GAME not in sys.path:
    sys.path.insert(0, GAME)
from tron.settings import service_data          # noqa: E402
from tron import rom_draw  # noqa: E402
from tron.service import EntryScreen, MenuScreen, flasher_names, menu_draw  # noqa: E402


class ServiceCase(TronTestCase):

    def setUp(self):
        super().setUp()
        self.shown = []
        self.machine.events.add_handler("tron_service_display", lambda **kwargs: self.shown.append(
            (kwargs["line0"], kwargs["line1"], kwargs["line2"])))

    @property
    def svc(self):
        return self.machine.modes["tron_service"]

    def press(self, button, wait=0.05):
        self.hit_and_release_switch("s_service_" + button)
        self.advance_time_and_run(wait)

    def enter(self):
        """SELECT shows the service entry screen (deff 3), SELECT again the main menu."""
        self.advance_time_and_run(1)
        self.press("select")
        self.assertTrue(self.svc.active)
        self.assertIsInstance(self.top, EntryScreen)
        self.press("select")

    @property
    def top(self):
        return self.svc.stack[-1]

    def goto(self, *path):
        """From the current menu, move to each item text with PLUS and open it with SELECT."""
        for text in path:
            menu = self.top
            self.assertIsInstance(menu, MenuScreen, text)
            texts = [i["text"] for i in menu.items()]
            self.assertIn(text, texts, menu.title)
            while texts[menu.pos % len(texts)] != text:
                self.press("plus")
            self.press("select")


class TestMenuTree(ServiceCase):

    def test_enter_from_attract_only_and_exit(self):
        self.enter()
        self.assertEqual(("SERVICE MENU", "PRESS 'SELECT' TO CONTINUE", "TRON L.E. V1.74 SYS. 1.63 HDW. 1"),
                         self.shown[-2])
        self.assertEqual(("MAIN MENU", "GO TO DIAGNOSTICS MENU", "1 OF 5"), self.shown[-1])
        self.assertFalse(self.machine.modes["attract"].active)     # no game start from the menu
        self.press("minus")                                       # wraps to the last item
        self.assertEqual("EXIT SERVICE MENU", self.shown[-1][1])
        self.press("select")
        self.assertFalse(self.svc.active)
        self.assertTrue(self.machine.modes["attract"].active)
        self.assertIn(1, [e["id"] for e in self.tron.trace.of("deff_start")])
        # BACK out of the main menu leaves too, as BACK on the entry screen does
        self.enter()
        self.press("back")
        self.assertFalse(self.svc.active)
        self.press("select")
        self.assertTrue(self.svc.active)
        self.press("back")
        self.assertFalse(self.svc.active)
        # no service menu during a game
        self.fill_trough()
        self.hit_and_release_switch("s_start_button")
        self.advance_time_and_run(2)
        self.press("select")
        self.assertFalse(self.svc.active)

    def test_every_menu_and_screen_opens(self):
        """Walk the whole tree: every visible item of every menu opens, renders and returns."""
        self.enter()
        seen_menus, seen_items = set(), set()

        def walk():
            menu = self.top
            seen_menus.add(menu.title)
            for item in list(menu.items()):
                if item["kind"] in ("back", "exit"):
                    continue
                self.goto(item["text"])
                seen_items.add(item["text"])
                if item["kind"] == "submenu":
                    walk()
                    self.goto(next(i["text"] for i in self.top.items() if i["kind"] == "back"))
                else:
                    self.assertTrue(self.shown[-1][0])
                    self.advance_time_and_run(1.2)                # cycling tests step once
                    self.press("plus")
                    self.press("minus")
                    self.press("back")
                    if self.top is not menu:                      # an editor took BACK as "cancel"
                        self.press("back")
                self.assertIs(self.top, menu)

        walk()
        expected_menus = {"MAIN MENU", "DIAGNOSTICS", "SWITCH MENU", "COIL MENU", "LAMP MENU", "FLASH LAMPS MENU",
                          "AUDITS", "ADJUSTMENTS", "UTILITIES", "INSTALLS", "RESETS", "USB", "GAME-SPECIFIC TESTS"}
        self.assertEqual(expected_menus, seen_menus)
        # every item of service_menu.md except the ones the ROM hides here (tournament, redemption,
        # software errors) and the help pages
        for name in expected_menus:
            for item in service_data()["menus"][name]:
                if item["kind"] in ("screen", "action", "submenu") and not item["shown_only_if"]:
                    self.assertIn(item["text"], seen_items)
        self.assertIn("DISPLAY HELP SCREEN", seen_items)

    def test_hidden_items_follow_their_conditions(self):
        self.tron.adj[45] = 1                                     # a ticket dispenser: redemption menu
        self.enter()
        texts = [i["text"] for i in self.top.items()]
        self.assertIn("GO TO REDEMPTION MENU", texts)
        self.assertNotIn("GO TO TOURNAMENT MENU", texts)
        self.goto("GO TO REDEMPTION MENU", "INSTALL REDEMPTION SYSTEM")
        self.assertEqual("NOT AVAILABLE", self.shown[-1][1])


class TestRomDraw(ServiceCase):
    """The screens as the ROM draws them (tron/rom_draw.py lists, drawn by tron/service_screen.gd)."""

    def test_menu_icon_row(self):
        """FUN_01037588: up to 7 icons centred, the selected one in its own image, the others dimmed (n + 1);
        more scroll 5 at a time between the MORE arrows (images 12, 13)."""
        draw = menu_draw([0, 2, 4, 6, 16], 1, "GO TO AUDITS MENU")
        self.assertEqual([{"i": 1, "x": 19, "y": 1}, {"i": 2, "x": 37, "y": 1}, {"i": 5, "x": 55, "y": 1},
                          {"i": 7, "x": 73, "y": 1}, {"i": 17, "x": 91, "y": 1}], draw[:5])
        self.assertEqual({"t": "GO TO AUDITS MENU", "f": 2, "x": 64, "y": 30, "a": 2}, draw[5])
        icons = list(range(20, 42, 2))                            # 11 items
        first = [d for d in menu_draw(icons, 0, "") if "i" in d]
        self.assertEqual([20, 23, 25, 27, 29, 13], [d["i"] for d in first])       # no left arrow yet
        self.assertEqual(19 + 5 * 18, first[-1]["x"])
        middle = [d["i"] for d in menu_draw(icons, 5, "") if "i" in d]
        self.assertEqual([12, 27, 29, 30, 33, 35, 13], middle)                    # selected item in the middle
        last = [d["i"] for d in menu_draw(icons, 10, "") if "i" in d]
        self.assertEqual([12, 33, 35, 37, 39, 40], last)                          # no right arrow at the end

    def test_entry_screen_and_main_menu_draw(self):
        self.advance_time_and_run(1)
        self.press("select")
        draw = self.svc.draw_items
        self.assertIn({"t": "V1.74", "f": 2, "x": 0, "y": 11, "a": 1}, draw)
        self.assertIn({"t": "HDW. 1", "f": 2, "x": 127, "y": 11, "a": 4}, draw)
        self.assertEqual("SERVICE MENU", next(d for d in draw if d.get("y") == 23)["t"])
        self.press("select")
        images = [d["i"] for d in self.svc.draw_items if "i" in d]
        self.assertEqual([0, 3, 5, 7, 17], images)                # DIAG selected, AUD ADJ UTIL QUIT dimmed
        self.press("plus")
        self.assertEqual([1, 2, 5, 7, 17], [d["i"] for d in self.svc.draw_items if "i" in d])

    def test_adjustment_value_blinks_while_edited(self):
        self.enter()
        self.goto("GO TO ADJUSTMENTS MENU", "STANDARD ADJUSTMENTS")
        texts = rom_draw.lines_of(self.svc.draw_items)
        self.assertIn("(INSTALLED, FACTORY DEFAULT)", texts)
        value = texts[2]
        self.press("select")
        seen = set()
        for _ in range(6):
            self.advance_time_and_run(0.13)
            seen.add(value in rom_draw.lines_of(self.svc.draw_items))
        self.assertEqual({True, False}, seen)
        self.press("back")


class TestDiagnostics(ServiceCase):

    def test_switch_tests_and_alerts(self):
        self.enter()
        self.goto("GO TO DIAGNOSTICS MENU", "GO TO SWITCH MENU", "SWITCH TEST")
        self.assertEqual("NONE", self.shown[-1][1])
        self.hit_switch_and_run("s_left_slingshot", 0.1)
        number = self.machine.switches["s_left_slingshot"].config["number"]
        self.assertEqual(("SWITCH TEST", "LEFT SLINGSHOT", "SWITCH #{}".format(number)), self.shown[-1])
        # the switch grid: a dot in the switch's cell while it is closed
        row, col = divmod(int(number) - 1, 16)
        cell = {"i": 0xa5, "x": 2 + 3 * col, "y": 6 + 3 * row}
        self.assertIn(cell, self.svc.draw_items)
        self.release_switch_and_run("s_left_slingshot", 0.1)
        self.assertEqual("LEFT SLINGSHOT", self.shown[-1][1])       # the last switch stays shown
        self.assertNotIn(cell, self.svc.draw_items)
        self.press("back")
        for name in ("s_trough_1_r", "s_trough_2", "s_trough_3", "s_trough_4_l"):
            self.machine.switch_controller.process_switch(name, 0, True)       # an empty machine
        self.goto("ACTIVE SWITCH TEST")
        self.assertEqual("NONE", self.shown[-1][1])            # nothing closed
        self.press("back")
        self.hit_switch_and_run("s_shooter_lane", 0.1)
        self.goto("ACTIVE SWITCH TEST")
        self.assertIn("SHOOTER", self.shown[-1][1])
        self.press("back")
        self.goto("SWITCH ALERTS")
        self.assertEqual("NOT ACTIVE", self.shown[-1][2])
        self.assertNotIn("LEFT_SLINGSHOT", " ".join(e.name.upper() for e in self.top.entries()))
        self.assertRegex(rom_draw.lines_of(self.svc.draw_items)[0], r"^TECHNICIAN ALERT - \(1/\d+\)$")
        # every switch seen: no alerts
        for switch in self.machine.switches.values():
            switch.last_change = 1
        self.press("plus")
        self.assertEqual("NO ALERTS", self.shown[-1][1])

    def test_coils_flashers_and_knocker(self):
        self.enter()
        self.goto("GO TO DIAGNOSTICS MENU", "GO TO COIL MENU", "SINGLE COIL TEST")
        coil = self.top.current()
        self.assertNotIn(coil.name, flasher_names())
        with mock.patch.object(coil, "pulse") as pulse:
            self.press("select")
            pulse.assert_called_once()
        self.press("back")
        self.goto("CYCLING COIL TEST")
        self.advance_time_and_run(3.5)
        self.assertGreaterEqual(len(self.top.fired), 4)
        self.press("back")
        self.goto("RETURN TO DIAGNOSTICS MENU", "GO TO FLASH LAMPS MENU", "SINGLE FLASH LAMP TEST")
        self.assertIn(self.top.current().name, flasher_names())
        self.press("select")
        self.assertEqual([self.top.current().name], self.top.fired)
        self.press("back")
        self.goto("CYCLING FLASH LAMP TEST")
        self.advance_time_and_run(2.5)
        self.assertTrue(all(name in flasher_names() for name in self.top.fired))
        self.press("back")
        self.goto("RETURN TO DIAGNOSTICS MENU", "KNOCKER TEST")
        self.assertEqual(("KNOCKER TEST", "PRESS 'SELECT' TO ACTIVATE", "KNOCKER"), self.shown[-1])
        self.press("select")
        self.assertEqual("0x019", self.tron.trace.of("sound")[-1]["call"])
        self.assertIn("ACTIVATING KNOCKER", rom_draw.lines_of(self.svc.draw_items))

    def test_lamp_tests_blink_at_service_priority(self):
        self.enter()
        self.goto("GO TO DIAGNOSTICS MENU", "GO TO LAMP MENU", "TEST ALL LAMPS")
        light = self.machine.lights["l_tron_n"]
        states = set()
        for _ in range(4):
            self.advance_time_and_run(0.5)
            states.add(any(e.key == "service" for e in light.stack))
        self.assertEqual({True, False}, states)
        self.press("back")
        self.assertFalse(any(e.key == "service" for e in light.stack))
        self.goto("LAMP COLUMN TEST")
        self.assertEqual(("LAMP COLUMN TEST", "COLUMN 1", "1 OF 9"), self.shown[-1])
        self.assertIn("COLUMN LAMPS TEST", rom_draw.lines_of(self.svc.draw_items))
        self.press("back")
        self.goto("LAMP ROW TEST")
        self.assertEqual("ROW 1", self.shown[-1][1])
        self.press("back")
        self.goto("SINGLE LAMP TEST")
        self.assertEqual(("SINGLE LAMP TEST", "TRO(N)", "LAMP #1"), self.shown[-1])

    def test_trough_sound_burn_in_motors_and_tubes(self):
        self.fill_trough()
        self.enter()
        self.goto("GO TO DIAGNOSTICS MENU", "BALL TROUGH TEST")
        self.assertEqual("TROUGH 1-4: X X X X", self.shown[-1][1])
        self.press("select", wait=1)
        self.assertEqual(3, self.machine.ball_devices["bd_trough"].balls)      # one ball sent to the shooter lane
        self.press("back")
        self.goto("SOUND/SPEAKER TEST")
        self.press("plus")
        self.press("select")
        self.assertEqual(self.top.current(), int(self.tron.trace.of("sound")[-1]["call"], 16))
        self.press("back")
        self.goto("BEGIN BURN-IN")
        self.assertIn("PRESS 'SELECT' TO START", rom_draw.lines_of(self.svc.draw_items))
        self.press("select")
        self.advance_time_and_run(2.5)
        self.assertEqual(("BURN-IN", "TOTAL BURN-IN TIME:", "0:03"), self.shown[-1])
        self.assertGreaterEqual(self.top.cycles, 3)
        self.assertIn(8, [e["id"] for e in self.tron.trace.of("leff_start")])
        self.press("back")
        self.goto("DOT MATRIX TEST")
        self.assertEqual("ALL DOTS ON", self.shown[-1][1])
        self.press("back")
        self.goto("GAME-SPECIFIC TESTS", "DISC MOTOR TEST")
        self.press("select")
        self.assertEqual("RUNNING", self.shown[-1][1])
        self.assertEqual("enabled", self.machine.coils["c_disc_motor_power"].hw_driver.state)
        self.press("minus")
        self.assertEqual("RUNNING REVERSE", self.shown[-1][1])
        self.press("back")
        self.assertEqual("disabled", self.machine.coils["c_disc_motor_power"].hw_driver.state)
        self.goto("3-BANK MOTOR TEST")
        self.assertIn("3_BANK_UP:-", self.shown[-1][2])
        self.press("back")
        self.goto("FIBER OPTIC LIGHT TUBE TEST")
        self.advance_time_and_run(2)
        self.assertGreaterEqual(len(self.tron.trace.of("tube_show_start")), 2)


class TestAuditsAndAdjustments(ServiceCase):

    def test_audit_screens_dump_and_resets(self):
        os_ = self.tron
        os_.audit(8, 4)                                           # 4 balls played
        os_.audit(9)                                              # 1 extra ball
        os_.audit(2, 3)                                           # 3 coins, left slot
        self.enter()
        self.goto("GO TO AUDITS MENU", "STANDARD AUDITS")
        while self.top.current() != 16:
            self.press("plus")
        self.assertEqual(("STANDARD AUDITS", "16 EXTRA BALL PERCENTAGE", "25%"), self.shown[-1])
        self.press("back")
        self.goto("EARNINGS AUDITS")
        self.assertEqual("01 TOTAL PAID CREDITS", self.shown[-1][1])
        self.press("back")
        self.goto("FEATURE AUDITS")
        self.assertEqual("73 DISC MULTIBALL STARTED", self.shown[-1][1])
        self.press("back")
        with tempfile.TemporaryDirectory() as tmp:
            self.svc.dump_path = os.path.join(tmp, "usb", "audits.txt")
            self.goto("DUMP AUDITS TO USB")
            self.press("select")
            text = open(self.svc.dump_path, encoding="utf-8").read()
        self.assertIn(" 14 TOTAL BALLS PLAYED", text)
        self.assertEqual(150, len(text.splitlines()))
        self.press("back")
        self.goto("RETURN TO MAIN MENU", "GO TO UTILITIES MENU", "GO TO RESETS MENU", "RESET COIN AUDITS")
        self.assertEqual(("RESET COIN AUDITS", "PRESS 'SELECT' TO RESET", "PRESS 'BACK' TO CANCEL"),
                         self.shown[-1])
        self.press("select")
        self.assertEqual(("RESET COIN AUDITS", "COMPLETE", "PRESS 'SELECT' TO CONTINUE"), self.shown[-1])
        self.assertEqual(0, os_.audits.value(10))                 # TOTAL COINS
        self.assertEqual(4, os_.audits.value(14))                 # game audits kept
        self.press("back")
        self.goto("RESET GAME AUDITS")
        self.press("select")
        self.assertEqual(0, os_.audits.value(14))

    def test_edit_adjustment_persists(self):
        os_ = self.tron
        self.enter()
        self.goto("GO TO ADJUSTMENTS MENU", "STANDARD ADJUSTMENTS")
        while self.top.current() != 31:
            self.press("plus")
        self.assertEqual(("STANDARD ADJUSTMENTS", "31 BALLS PER GAME", "3 (FACTORY)"), self.shown[-1])
        self.press("select")
        self.press("plus")
        self.press("plus")
        self.assertEqual("> 5", self.shown[-1][2])
        self.press("back")                                        # BACK drops the change
        self.assertEqual(3, os_.adj[31])
        self.press("select")
        self.press("minus")
        self.press("select")
        self.assertEqual(2, os_.adj[31])
        os_.adj[31] = 10
        self.press("select")
        self.press("plus")                                        # wraps 10 -> 1
        self.assertEqual("> 1", self.shown[-1][2])
        self.press("minus")                                       # and back 1 -> 10
        self.press("select")
        self.assertEqual(10, os_.adj[31])
        os_.adj[31] = 2
        var = self.machine.variables.machine_vars["balls_per_game"]
        self.assertEqual((2, True), (var["value"], var["persist"]))
        self.press("back")
        self.goto("FEATURE ADJUSTMENTS")
        self.assertEqual("65 POP BUMPER DIFFICULTY", self.shown[-1][1])
        self.press("select")
        self.press("minus")
        self.press("minus")
        self.assertEqual("> HARD", self.shown[-1][2])                # 1 -> 0 -> wraps to 2
        self.press("select")
        self.assertEqual(2, os_.adj[65])

    def test_display_adjustments(self):
        """ADJUSTMENTS > DISPLAY ADJUSTMENTS (not in the ROM): TEXT GLOW and TEXT SIZE of the HD display, in
        percent. The value being edited goes to the display at once (machine vars dmd_text_glow, dmd_text_size,
        which GMC receives); BACK puts the stored one back; SELECT stores it (persisted); the factory value and
        RESET FACTORY SETTINGS leave the display's own start value (-1)."""
        os_ = self.tron
        var = self.machine.variables.get_machine_var
        self.assertEqual((-1, -1), (var("dmd_text_glow"), var("dmd_text_size")))
        self.enter()
        self.goto("GO TO ADJUSTMENTS MENU")
        texts = [i["text"] for i in self.top.items()]
        self.assertEqual(texts.index("FEATURE ADJUSTMENTS") + 1, texts.index("DISPLAY ADJUSTMENTS"))
        self.goto("DISPLAY ADJUSTMENTS")
        self.assertEqual(("DISPLAY ADJUSTMENTS", "01 TEXT GLOW", "80% (FACTORY)"), self.shown[-1])
        self.assertIn("(INSTALLED, FACTORY DEFAULT)", rom_draw.lines_of(self.svc.draw_items))
        self.press("select")
        self.press("plus")
        self.assertEqual("> 90%", self.shown[-1][2])
        self.assertEqual(90, var("dmd_text_glow"))                # previewed on the display
        self.press("back")
        self.assertEqual((80, -1), (os_.display_settings[1], var("dmd_text_glow")))
        self.press("select")
        for _ in range(9):
            self.press("minus")
        self.assertEqual("> OFF", self.shown[-1][2])             # stops at the bottom
        self.press("select")
        self.assertEqual((0, 0, 0), (os_.display_settings[1], var("dmd_text_glow"), var("dmd_text_glow_setting")))
        self.assertTrue(self.machine.variables.machine_vars["dmd_text_glow_setting"]["persist"])
        self.press("plus")                                        # TEXT SIZE
        self.assertEqual(("DISPLAY ADJUSTMENTS", "02 TEXT SIZE", "85% (FACTORY)"), self.shown[-1])
        self.press("select")
        for _ in range(5):
            self.press("plus")
        self.press("select")
        self.assertEqual((110, 110), (os_.display_settings[2], var("dmd_text_size")))
        self.press("select")                                      # 110% is the top (owner's choice)
        self.press("plus")
        self.assertEqual("> 110%", self.shown[-1][2])
        self.press("back")
        self.press("select")                                      # back to the factory value: the start value
        for _ in range(5):
            self.press("minus")
        self.press("select")
        self.assertEqual((85, -1), (os_.display_settings[2], var("dmd_text_size")))
        self.press("select")                                      # leaving while editing drops the preview
        self.press("plus")
        self.assertEqual(90, var("dmd_text_size"))
        self.press("back")
        self.press("back")
        self.assertEqual(-1, var("dmd_text_size"))
        self.svc.factory_reset()
        self.assertEqual((80, -1), (os_.display_settings[1], var("dmd_text_glow")))

    def test_installs_and_factory_reset(self):
        os_ = self.tron
        self.enter()
        self.goto("GO TO UTILITIES MENU", "GO TO INSTALLS MENU", "INSTALL 5-BALL")
        self.press("select")
        self.assertEqual(("5-BALL", "INSTALLED", "PRESS 'SELECT' TO CONTINUE"), self.shown[-1])
        self.press("select")                                      # CONTINUE: back to the menu
        self.goto("INSTALL 5-BALL")
        self.assertEqual("(INSTALLED)", self.shown[-1][1])
        self.assertEqual(5, os_.adj[31])
        self.press("back")
        self.goto("INSTALL ADD-A-BALL")
        self.press("select")
        self.assertEqual((3, 4, 0, 9, 11), (os_.adj[13], os_.adj[23], os_.adj[25], os_.adj[26], os_.adj[30]))
        self.press("back")
        self.goto("INSTALL COMPETITION")
        self.press("select")
        self.assertEqual((1, 1, 0), (os_.adj[34], os_.adj[42], os_.adj[63]))
        self.press("back")
        self.goto("INSTALL HARD")                                 # empty list in 1.74
        self.press("select")
        self.assertEqual(1, os_.adj[42])
        self.press("back")
        self.goto("INSTALL FACTORY")
        self.press("select")
        self.assertTrue(all(os_.adj[n] == os_.adj.default(n) for n in os_.adj))
        os_.adj[31] = 4
        os_.audit(8)
        os_.credit_model.add(2)
        self.press("back")
        self.goto("RETURN TO UTILITIES MENU", "GO TO RESETS MENU", "RESET FACTORY SETTINGS")
        self.press("select")
        self.assertEqual((3, None, 0, -1), (os_.adj[31], os_.audits.get(8), os_.credit_model.credits,
                                            os_.credit_model.counter))

    def test_custom_message_date_time_and_usb(self):
        os_ = self.tron
        self.enter()
        self.goto("GO TO UTILITIES MENU", "ENTER CUSTOM MESSAGE")
        self.press("plus")                                        # ' ' -> 'A'
        self.press("plus")                                        # 'B'
        for _ in range(16):
            self.press("select")
        self.assertEqual("B", self.machine.variables.get_machine_var("custom_message_text"))
        self.assertTrue(self.machine.variables.machine_vars["custom_message_text"]["persist"])
        self.goto("SET DATE/TIME")
        self.assertEqual("SET YEAR", self.shown[-1][0])
        self.assertRegex(self.shown[-1][2], r"^\d{1,2}:\d\d [AP]M$")       # adj 3 = 12-HOUR
        self.press("plus")                                        # year + 1
        self.press("select")
        for field in ("MONTH", "DAY", "HOUR", "MINUTE"):          # +1 and -1 on every other field
            self.assertEqual("SET " + field, self.shown[-1][0])
            self.press("plus")
            self.press("minus")
            self.press("select")
        offset = self.machine.variables.get_machine_var("clock_offset")
        self.assertAlmostEqual(365 * 86400, offset, delta=2 * 86400)
        os_.adj[3] = 1                                            # 24-HOUR
        self.goto("SET DATE/TIME")
        self.assertRegex(self.shown[-1][2], r"^\d\d:\d\d$")
        self.press("back")
        self.goto("SET CUSTOM PRICING")
        self.assertEqual(("COIN UNITS", "> 1"), tuple(self.shown[-1][1:]))
        self.press("minus")                                       # never below 1
        self.press("select")
        self.assertEqual(("UNITS PER CREDIT", "> 3"), tuple(self.shown[-1][1:]))
        self.press("minus")
        self.press("select")                                      # stored, CUSTOM pricing
        self.assertEqual((64, 1, 2), (os_.adj[28], self.machine.variables.get_machine_var("custom_coin_units"),
                                      self.machine.variables.get_machine_var("custom_units_per_credit")))
        self.goto("SET CUSTOM PRICING")
        self.press("plus")
        self.press("back")                                        # dropped
        self.assertEqual(1, self.machine.variables.get_machine_var("custom_coin_units"))
        self.goto("GO TO USB MENU", "UPDATE GAME CODE")
        self.assertEqual(("GAME CODE UPDATE", "NO UPDATE FOUND"), self.shown[-1][:2])

    def test_slide_sent_over_bcp(self):
        sent = []
        bridge = self.tron.media
        with mock.patch.object(bridge, "connected", lambda need_data=True: not need_data), \
                mock.patch.object(self.machine, "bcp", mock.Mock(), create=True):
            self.machine.bcp.interface.bcp_trigger = lambda **kw: sent.append(kw)
            self.machine.bcp.interface.bcp_trigger_client = lambda client, **kw: sent.append(kw)
            self.enter()
            self.press("back")
        sent = [kw for kw in sent if "service" in (kw.get("settings") or {})]
        plays = [kw for kw in sent if kw["settings"]["service"]["action"] in ("play", "update")]
        self.assertEqual("play", plays[0]["settings"]["service"]["action"])
        self.assertEqual("SERVICE MENU", plays[0]["line0"])
        # later screens update the slide in place (a remove and play would flash the slides below)
        self.assertEqual("update", plays[1]["settings"]["service"]["action"])
        self.assertEqual("MAIN MENU", plays[1]["line0"])
        self.assertIn({"t": "GO TO DIAGNOSTICS MENU", "f": 2, "x": 64, "y": 30, "a": 2}, plays[1]["draw"])
        self.assertEqual("remove", sent[-1]["settings"]["service"]["action"])


class TestPersistence(TronTestCase):
    """A power cycle: MPF reloads the machine vars and the audit data file."""

    def _get_mock_data(self):
        return {"machine_vars": {"balls_per_game": {"value": 1, "persist": True},
                                 "tilt_warnings": {"value": 0, "persist": True},
                                 "dmd_text_glow_setting": {"value": 120, "persist": True}},
                "tron_audits": {"counters": {8: 40, 9: 2}, "extra": {"score_total": 1000}}}

    def test_settings_and_audits_survive_power_cycle(self):
        os_ = self.tron
        self.assertEqual((1, 0, 5), (os_.adj[31], os_.adj[32], os_.adj[38]))   # persisted, persisted, default
        self.assertEqual(40, os_.audits[8])
        self.assertEqual(5, os_.audits.value(16))                 # 2 / 40 extra balls
        os_.audit(8)
        self.assertEqual({8: 41, 9: 2}, os_.audits.store.written_data["counters"])
        self.fill_trough()
        self.hit_and_release_switch("s_start_button")
        self.advance_time_and_run(2)
        self.assertEqual(1, self.machine.game.balls_per_game)     # adj 31 drives MPF's game

    def test_display_settings_survive_power_cycle(self):
        """DISPLAY ADJUSTMENTS: the stored text glow reaches the display at start (machine var dmd_text_glow)."""
        self.assertEqual(120, self.tron.display_settings[1])
        self.assertEqual(120, self.machine.variables.get_machine_var("dmd_text_glow"))
        self.assertEqual(-1, self.machine.variables.get_machine_var("dmd_text_size"))

    def test_override_is_not_stored(self):
        adj = self.tron.adj
        adj.override(32, 3)                                       # a live scenario's "adj" command
        self.assertEqual(3, adj[32])
        self.assertEqual(0, self.machine.variables.get_machine_var("tilt_warnings"))
        adj[32] = 1                                               # an operator change replaces it
        self.assertEqual(1, adj[32])
