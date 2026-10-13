"""Ball counts on a table that moves balls like the VPX table: trough ball stack (jam switch pulsed on each
eject), shooter lane, and a scoop ball stack whose one switch stays on for any number of balls."""
from tests.tron_test import TronTestCase

TROUGH = ("s_trough_1_r", "s_trough_2", "s_trough_3", "s_trough_4_l")


class Table:
    """Physical balls: trough stack (no entry switch, jam pulse on each eject), shooter lane, VUK stack
    (one switch for any number of balls), playfield."""

    def __init__(self, test):
        self.t = test
        self.m = test.machine
        self.trough = 4
        self.shooter = 0
        self.vuk = 0
        self.pf = 0
        self.vuk_stack = True
        for name, fn in (("c_trough_up_kicker", self.kick_trough), ("c_auto_launch", self.launch),
                         ("c_video_game_eject", self.kick_vuk)):
            self.m.coils[name].hw_driver.pulse = (lambda f: lambda *a, **k: f())(fn)
        self.update()

    def sw(self, name, on):
        self.m.switch_controller.process_switch(name, 1 if on else 0, True)

    def update(self):
        for i, name in enumerate(TROUGH):
            if bool(self.m.switches[name].state) != (i < self.trough):
                self.sw(name, i < self.trough)
        if bool(self.m.switches["s_shooter_lane"].state) != bool(self.shooter):
            self.sw("s_shooter_lane", self.shooter)
        if bool(self.m.switches["s_video_game_eject"].state) != bool(self.vuk):
            self.sw("s_video_game_eject", self.vuk)

    def delay(self, s, fn):
        self.m.clock.schedule_once(lambda *a: fn(), s)

    def kick_trough(self):
        if not self.trough:
            return
        self.trough -= 1
        self.update()
        self.sw("s_trough_jam", 1)
        self.delay(.04, lambda: self.sw("s_trough_jam", 0))

        def arrive():
            self.shooter += 1
            self.update()
        self.delay(.3, arrive)

    def launch(self):
        if not self.shooter:
            return
        self.shooter -= 1
        self.update()
        self.delay(.8, self.on_playfield)

    def on_playfield(self):
        self.pf += 1
        self.sw("s_left_orbit", 1)
        self.delay(.05, lambda: self.sw("s_left_orbit", 0))

    def kick_vuk(self):
        if not self.vuk:
            return
        self.vuk -= 1
        self.update()
        self.delay(.5, self.on_playfield)

    def drain(self):
        assert self.pf > 0
        self.pf -= 1
        self.trough += 1
        self.update()

    def to_vuk(self):
        assert self.pf > 0
        self.pf -= 1
        if self.vuk and not self.vuk_stack:
            self.pf += 1          # a real VUK: the ball bounces out
            return
        self.vuk += 1
        self.update()

    @property
    def in_play(self):
        return 4 - self.trough


class TestBallTracking(TronTestCase):

    def get_platform(self):
        return "virtual"

    def start_game(self):
        self.table = Table(self)
        self.advance_time_and_run(2)
        self.hit_and_release_switch("s_start_button")
        self.advance_time_and_run(3)
        self.table.launch()                  # the player plunges
        self.advance_time_and_run(1)
        self.hit_and_release_switch("s_zen_rollover")
        self.advance_time_and_run(1)
        self.assertEqual(1, self.table.pf)
        return self.tron

    def assertCounts(self, balls):
        self.assertEqual(balls, self.table.in_play)
        self.assertEqual(balls, self.machine.game.balls_in_play)

    def test_second_ball_swallowed_by_the_scoop(self):
        """The table's scoop keeps a second ball without a switch change; both come out, the count holds."""
        os_ = self.start_game()
        os_.pd.lc_lit = 1
        self.assertTrue(os_.features_by_name["light_cycle"].mb_start(False, False))
        self.advance_time_and_run(8)
        self.assertCounts(2)
        self.table.to_vuk()
        self.advance_time_and_run(.3)
        self.table.to_vuk()
        self.advance_time_and_run(15)
        self.assertEqual((0, 2), (self.table.vuk, self.table.pf))
        self.assertCounts(2)
        self.table.drain()
        self.advance_time_and_run(3)
        self.assertCounts(1)
        self.assertFalse(os_.flag(0x2b))                  # one ball left: Light Cycle ends

    def test_later_stack_adds_no_ball(self):
        """ROM quirk (rom_differences.md): Quorra started at a later scoop shot during Light Cycle asks for
        balls in play + 1 without the ball held in the scoop, so no ball is added [0x0001e738]."""
        os_ = self.start_game()
        os_.pd.lc_lit = 1
        self.assertTrue(os_.features_by_name["light_cycle"].mb_start(False, False))
        self.advance_time_and_run(20)                     # save and grace over
        os_.hook("vuk_lit_add", 2)                        # Quorra lit
        self.table.to_vuk()
        self.advance_time_and_run(20)
        self.assertTrue(os_.flag(0x29) and os_.flag(0x2b))
        self.assertCounts(2)

    def test_eol_add_a_ball_counts_like_the_rom(self):
        """multiball_add_balls [0x0001eeb0] adds to the ROM's balls in play, which leaves out a ball held in
        the scoop: the held ball is the one that comes back into play."""
        os_ = self.start_game()
        eol = os_.features_by_name["end_of_line"]
        self.assertTrue(eol.start())
        self.advance_time_and_run(20)                     # save and grace over
        self.assertCounts(2)
        self.table.to_vuk()
        self.advance_time_and_run(.2)
        self.assertTrue(os_.ball_held)
        calls = []
        start = os_.multiball_start
        os_.multiball_start = lambda balls, *a: (calls.append(balls), start(balls, *a))[1]
        eol.aab_left, eol.mask = 1, 7
        self.assertTrue(eol.jackpot_shot(2))              # the disc: add-a-ball
        self.assertEqual([2], calls)
        self.advance_time_and_run(15)
        self.assertCounts(2)

    def test_lost_ball_feed_then_the_stuck_ball_drains(self):
        """ROM-accurate (rom_differences.md): PINBALL MISSING serves a ball for the stuck one; when the stuck
        ball drains later, the ball ends with the served ball still on the playfield [0x0001f79c]."""
        self.start_game()
        self.advance_time_and_run(120)                    # 5 failed searches
        self.assertEqual(2, self.table.in_play)
        self.assertEqual(1, self.machine.game.balls_in_play)
        self.table.drain()
        self.advance_time_and_run(5)
        self.assertEqual(2, self.machine.game.player.ball)
