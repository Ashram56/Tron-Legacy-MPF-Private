"""The coin door (switch s_coin_door_open): opening it cuts the coil power, and the ROM's power handler shows the
"50V / 20V DISABLED" warning, deff 4 [FUN_00007bc4, deff_004_50v_20v_disabled 0x01036f1c]. Closing the door
or pressing BACK takes it away [FUN_00007c08, 0x0000fc20]."""
from tests.test_adjustments import AdjCase
from tron.os_layer import POWER_OFF_DIM_TICKS, TICK


class TestCoinDoor(AdjCase):

    def draws(self):
        seen = []
        self.tron.media.deff_draw = lambda deff_id, priority, draw: seen.append((deff_id, priority, draw))
        return seen

    def test_warning_in_attract_until_the_door_closes(self):
        os_ = self.tron
        drawn = self.draws()
        self.hit_switch_and_run("s_coin_door_open", 2)
        self.assertEqual([4], [d for d in self.deffs() if d == 4])
        self.assertEqual(4, os_.display.fg)
        self.assertEqual(["0x010"] * 5, [c for c in self.sounds() if c == "0x010"])     # five beeps as it blinks
        self.advance_time_and_run(POWER_OFF_DIM_TICKS * TICK - 2 - 0.1)
        self.assertEqual([], drawn)
        self.advance_time_and_run(0.2)                         # then the whole screen dims to level 6
        self.assertEqual(1, len(drawn))
        deff_id, priority, draw = drawn[0]
        self.assertEqual((4, 247), (deff_id, priority))
        self.assertEqual(["50V / 20V DISABLED", "CLOSE COIN DOOR", "OR PULL INTERLOCK SWITCH", "TO RESTORE POWER"],
                         [d["t"] for d in draw])
        self.assertEqual({6}, {d["l"] for d in draw})
        self.assertEqual([(8, 9), (2, 16), (2, 22), (2, 28)], [(d["f"], d["y"]) for d in draw])
        self.advance_time_and_run(60)
        self.assertEqual(4, os_.display.fg)                    # it never ends by itself
        self.release_switch_and_run("s_coin_door_open", 0.1)
        self.assertIsNone(os_.display.fg)
        self.assertIn(4, [e["id"] for e in os_.trace.of("deff_stop")])

    def test_back_takes_the_warning_away(self):
        os_ = self.tron
        self.hit_switch_and_run("s_coin_door_open", 1)
        self.hit_and_release_switch("s_service_back")
        self.advance_time_and_run(0.1)
        self.assertNotEqual(4, os_.display.fg)
        self.assertIn("0x009", self.sounds())
        self.assertEqual(0, os_.audits[0x24])                   # no service credit this time
        self.hit_and_release_switch("s_service_back")           # warning gone: BACK is a service credit again
        self.advance_time_and_run(0.1)
        self.assertEqual(1, os_.audits[0x24])

    def test_service_menu_with_the_door_open(self):
        os_ = self.tron
        self.hit_switch_and_run("s_coin_door_open", 1)
        self.hit_and_release_switch("s_service_select")         # SELECT opens the menu over the warning
        self.advance_time_and_run(0.1)
        self.assertTrue(os_.in_service)
        self.hit_and_release_switch("s_service_back")           # BACK inside the menu leaves it
        self.advance_time_and_run(0.5)
        self.assertFalse(os_.in_service)
        self.assertNotIn("0x009", self.sounds())

    def test_no_warning_when_the_door_opens_in_the_menu(self):
        os_ = self.tron
        self.hit_and_release_switch("s_service_select")
        self.advance_time_and_run(0.1)
        self.assertTrue(os_.in_service)
        self.hit_switch_and_run("s_coin_door_open", 1)          # the service menu's deff 3 (253) has the display
        self.assertNotIn(4, self.deffs())

    def test_warning_in_play_over_the_game_display(self):
        os_ = self.start_game()
        self.hit_switch_and_run("s_coin_door_open", 1)
        self.assertEqual(4, os_.display.fg)
        self.hit_and_release_switch("s_zen_rollover")           # the game goes on behind it (priority 247)
        self.advance_time_and_run(1)
        self.assertEqual(4, os_.display.fg)
        self.release_switch_and_run("s_coin_door_open", 1)
        self.assertNotEqual(4, os_.display.fg)
        self.assertEqual(19, os_.display.bg)                    # the score display is back

    def test_reopened_door_restarts_the_dim_timer(self):
        drawn = self.draws()
        self.hit_switch_and_run("s_coin_door_open", 20)
        self.release_switch_and_run("s_coin_door_open", 1)
        self.hit_switch_and_run("s_coin_door_open", POWER_OFF_DIM_TICKS * TICK - 21 + 5)
        self.assertEqual([], drawn)                             # the first opening's timer did nothing
        self.advance_time_and_run(20)
        self.assertEqual(1, len(drawn))


class TestServiceInGame(AdjCase):
    """SELECT in a game (not in the ROM, which suspends the game): a second SELECT ends it into the menu."""

    def confirms(self):
        seen = []
        media = self.tron.media
        media.confirm_show = lambda draw: seen.append([d["t"] for d in draw])
        media.confirm_hide = lambda: seen.append(None)
        return seen

    def test_select_twice_ends_the_game_into_the_menu(self):
        os_ = self.start_game()
        shown = self.confirms()
        self.hit_and_release_switch("s_service_select")
        self.advance_time_and_run(0.5)
        self.assertEqual([["END GAME?", "PRESS 'SELECT' FOR SERVICE MENU", "PRESS 'BACK' TO CANCEL"]], shown)
        self.assertModeRunning("game")
        self.hit_and_release_switch("s_service_select")
        self.advance_time_and_run(2)
        self.assertModeNotRunning("game")
        self.assertTrue(os_.in_service)
        self.assertNotIn(38, self.deffs())                     # no match

    def test_back_or_timeout_keeps_the_game(self):
        os_ = self.start_game()
        shown = self.confirms()
        self.hit_and_release_switch("s_service_select")
        self.advance_time_and_run(0.5)
        self.hit_and_release_switch("s_service_back")          # no
        self.advance_time_and_run(0.5)
        self.assertEqual(None, shown[-1])
        self.assertEqual(0, os_.audits[0x24])                  # and no service credit
        self.hit_and_release_switch("s_service_select")
        self.advance_time_and_run(6)                           # unanswered: the question goes away
        self.assertEqual(None, shown[-1])
        self.hit_and_release_switch("s_service_select")        # so this is a new first press
        self.advance_time_and_run(0.5)
        self.assertModeRunning("game")
        self.assertFalse(os_.in_service)
