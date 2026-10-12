"""End of Line Multiball, a.k.a. Daft Punk Multiball (assets/rules/modes/end_of_line_multiball.md,
daft_punk_multiball.md: one mode), and the End of Line combo jackpot (combos.md "End of Line combo
jackpot": light on the right ramp, collect at the VUK).

Letters: each qualifying left ramp lights the next letter of DAFT, each right ramp the next of PUNK;
both words = one set [eol_letters_ramp 0x010042d0]. Adj 83 sets light the first multiball of the
game, adj 84 the later ones; set number adj 85 (game total) lights the extra ball once (flag 0x28).
Lit = game flag 0x26, started at the VUK (2-ball multiball, flag 0x27). While running or in the
312-tick grace (tasks 0xb0/0xb1) every listed switch scores the switch value, the left ramp a
jackpot, the right ramp a double jackpot, the disc 200,000 + level + add-a-balls.

Hooks called by the switch layer: eol_shot_score, eol_ramp_jackpot(shot), eol_disc_jackpot(shot),
eol_letter(side), eol_vuk, eol_combo_jackpot (collect), eol_combo_jackpot_light.
The jackpot value itself (pd.eol_combo_jackpot, 500,000 at each ball start, grown by named combos)
belongs to the combos feature. For others: eol_running() (flag 0x27), eol_running_or_grace()
(0x01004c30, Disc/Recognizer), eol_running_or_grace_a() (Recognizer bank motor, 0x0102227c).
"""
from tron.features import Feature

ORDER = 60

LIT, RUNNING, EB_GIVEN = 0x26, 0x27, 0x28
SHOT_BITS = (1, 2, 4)                 # table 0x040d25a8: 0 left ramp, 1 right ramp, 2 disc
INTRO_TASK, GRACE_A, GRACE_B, TOTAL_TASK = 0xa6, 0xb0, 0xb1, 0x4f
COMBO_JACKPOT_LIT_A, COMBO_JACKPOT_LIT_B, COMBO_JACKPOT_SHOW = 0xcf, 0xd0, 0x87
# deff 56 chains its speech with snd_play_chain: 0x025 after sample 0x320 (2.56 s), 0x026 after 0x321
# (2.33 s) (callouts/samples_index.csv; traces/end_of_line_multiball.jsonl 58.01 -> 60.57 -> 62.92)
INTRO_SPEECH_CHAIN = ((2.56, 0x025), (2.33, 0x026))
TOTAL_WAIT_TICKS = 169                # ball end waits up to 169 ticks for flag-0x2000 tasks (task 0x4f)
MUSIC_PRIORITY = 7                    # background rule priority [eol_init_rules 0x01006298]


class EndOfLine(Feature):
    name = "end_of_line"
    HOOKS = ("player_first_ball", "ball_end", "ball_end_wait", "multiball_end",
             "eol_shot_score", "eol_ramp_jackpot", "eol_disc_jackpot", "eol_letter",
             "eol_vuk", "eol_combo_jackpot", "eol_combo_jackpot_light", "eol_running",
             "eol_running_or_grace", "eol_running_or_grace_a")

    def __init__(self, os_):
        super().__init__(os_)
        self.mask = self.level = self.aab_left = self.aab_count = 0
        self.switch_value = 10000
        self.total = 0
        self.total_pending = False
        # lamp/tube rules [eol_init_rules 0x01006298]; the ROM starts leff 60 before leff 59
        os_.lamp_rule(self.lit_rule, leff=57, order=0x01005198)
        os_.lamp_rule(self.background_on, leff=60, order=0x010055d8)
        os_.lamp_rule(self.background_on, leff=59, order=0x010055d8)
        os_.lamp_rule(self.background_on, tube=88, order=0x010055d8)
        # deff + music rule [0x01005610]: deff 57, music 0x20 + (level & 3), priority 7
        os_.deff_rule(self.background_on, 57, music=lambda: 0x20 + (self.level & 3), priority=MUSIC_PRIORITY)
        os_.deff_live((57,), lambda: {"value": self.switch_value})    # deff 57 [0x01005524]: eol_switch_value
        # End of Line combo jackpot lit (task 0xcf) [leff rule 0x01003914]
        os_.lamp_rule(lambda: os_.task_running(COMBO_JACKPOT_LIT_A), leff=161, order=0x01003914)

    # ------------------------------------------------------------------ per player / per ball

    def player_first_ball(self):
        """eol_game_reset 0x01004198 (+ event 0x26 handler 0x01004b68)."""
        pd = self.pd
        pd.eol_left = pd.eol_right = 0
        pd.eol_times_lit = pd.eol_sets = pd.eol_sets_total = 0
        pd.eol_starts = 0

    # ------------------------------------------------------------------ conditions

    def can_start(self):
        """eol_multiball_can_start 0x01004c68: no multiball and no Sea of Simulation running."""
        return not self.os.any_multiball() and not self.os.flag(0x34)

    def active(self):
        """eol_running_or_grace 0x01004c30."""
        return self.os.flag(RUNNING) or self.os.task_running(GRACE_A) or self.os.task_running(GRACE_B)

    def eol_running_or_grace(self):
        return self.active()

    def eol_running(self):
        """eol_multiball_running 0x01004be8."""
        return self.os.flag(RUNNING)

    def eol_running_or_grace_a(self):
        """0x01004bfc: running or in the first grace task (keeps the Recognizer 3-bank down)."""
        return self.os.flag(RUNNING) or self.os.task_running(GRACE_A)

    def lit_rule(self):
        """eol_lit_rule 0x01005198 (leff 57: flashers 17/18 while lit)."""
        return self.can_start() and self.os.flag(LIT)

    def background_on(self):
        """eol_background_rule 0x010055d8: running, and the intro is not still waiting in the queue."""
        if not self.os.flag(RUNNING):
            return False
        return not any(s.task_id == INTRO_TASK for s in self.os.display.shows)

    # ------------------------------------------------------------------ DAFT / PUNK letters

    def eol_letter(self, side):
        """eol_letters_ramp 0x010042d0: side 0 = left ramp (DAFT), 1 = right ramp (PUNK)."""
        os_, pd = self.os, self.pd
        if os_.flag(LIT) or os_.any_multiball() or os_.flag(0x34):
            return False
        before = (pd.eol_left, pd.eol_right)
        if side == 0:
            pd.eol_left = min(pd.eol_left + 1, 4)
        else:
            pd.eol_right = min(pd.eol_right + 1, 4)
        after = (pd.eol_left, pd.eol_right)
        needed = os_.adj_value(83) if pd.eol_times_lit == 0 else os_.adj_value(84)
        eb_adj = os_.adj_value(85)
        flags = 0
        if pd.eol_left >= 4 and pd.eol_right >= 4:
            pd.eol_sets = min(pd.eol_sets + 1, 0xff)
            if pd.eol_sets >= needed and not os_.flag(LIT):          # eol_light_multiball 0x01004bb0
                os_.flag_set(LIT)
                pd.eol_times_lit = min(pd.eol_times_lit + 1, 0xff)
                pd.eol_sets = 0
                flags |= 2
            pd.eol_sets_total = min(pd.eol_sets_total + 1, 0xff)
            if self.extra_ball_check(pd.eol_sets_total):
                flags |= 1
            pd.eol_left = pd.eol_right = 0
        mb_left = needed - pd.eol_sets
        more, what = mb_left, 8                                       # "LIGHT MULTIBALL"
        if pd.eol_sets_total < eb_adj:
            eb_left = eb_adj - pd.eol_sets_total
            if eb_left < mb_left:
                more, what = eb_left, 4                               # "LIGHT EX. BALL"
            elif eb_left == mb_left:
                what = 0xc                                            # "LIGHT M.B. + E.B."
        os_.deff_start(55, before=before, after=after, flags=flags | what, more=more,
                       screen=self.letters_screen(flags | what))
        return True

    @staticmethod
    def letters_screen(flags):
        """deff 55's text by its flags [0x0100461c] (rom_layout.SCREENS): 0 MULTIBALL + E.B. / ARE LIT,
        1 EXTRA BALL / IS LIT, 5 MULTIBALL / IS LIT, else %u MORE TO and 2 LIGHT MULTIBALL, 3 LIGHT EX.
        BALL, 4 LIGHT M.B. + E.B. or 6 nothing below."""
        if flags & 3 == 3:
            return 0
        if flags & 1:
            return 1
        if flags & 2:
            return 5
        if flags & 0xc == 0xc:
            return 4
        return 3 if flags & 4 else 2 if flags & 8 else 6

    def extra_ball_check(self, sets_total):
        """eol_extra_ball_check 0x01004238: the extra ball is lit once per game at set number adj 85."""
        os_ = self.os
        adj = os_.adj_value(85)
        if os_.flag(EB_GIVEN) or not adj or adj != sets_total:
            return False
        if not os_.hook("vuk_lit_add", 1, True):
            return False
        os_.flag_set(EB_GIVEN)
        return True

    # ------------------------------------------------------------------ start at the VUK

    def eol_vuk(self):
        """eol_vuk_start_if_lit 0x01004ddc."""
        if self.os.flag(LIT) and self.start():
            self.os.flag_clear(LIT)
            return True
        return False

    def start(self):
        """eol_multiball_start 0x01004cc0."""
        os_, pd = self.os, self.pd
        if not self.can_start():
            return False
        n = os_.rom_balls_in_play()
        if not os_.multiball_start(2 if n == 0 else n + 1, 625, 125):
            return False
        self.mask, self.level, self.aab_left, self.aab_count = 7, 0, 2, 0
        self.switch_value = 10000
        os_.flag_set(RUNNING)
        pd.eol_starts = min(pd.eol_starts + 1, 0xff)
        os_.audit(0x8e)
        self.total = os_.score_add(100000)
        os_.show(INTRO_TASK, 56, on_start=self.intro_started)     # task_a6_eol_intro 0x01004c94
        os_.request_refresh()
        return True

    def intro_started(self):
        """deff 56 plays speech 0x024 and chains 0x025 and 0x026 after it (snd_play_chain)."""
        delay = 0.0
        for seconds, call in INTRO_SPEECH_CHAIN:
            delay += seconds
            self.machine.clock.schedule_once(lambda c=call: self.os.sound(c), delay)

    # ------------------------------------------------------------------ scoring while active

    def eol_shot_score(self):
        """eol_shot_score 0x01005074: every listed switch scores the switch value."""
        if not self.active():
            return False
        self.total += self.os.score_add(self.switch_value)
        return True

    def jackpot_value(self):
        """eol_jackpot_value 0x01004e10."""
        return min(500000 + 25000 * self.level, 1250000)

    def eol_ramp_jackpot(self, shot):
        return self.jackpot_shot(shot)

    def eol_disc_jackpot(self, shot):
        return self.jackpot_shot(shot)

    def jackpot_shot(self, shot):
        """eol_jackpot_shot 0x01004e94: shot 0 left ramp (jackpot), 1 right ramp (double), 2 disc."""
        os_ = self.os
        bit = SHOT_BITS[shot]
        if not self.active() or not self.mask & bit:
            return False
        if bit in (1, 2):
            self.mask &= ~bit
            if not self.mask & 3:
                self.mask = 7
            points = os_.score_add(self.jackpot_value() * bit)       # bit 2 = double jackpot
            self.total += points
            os_.deff_start(58 if bit == 1 else 59, value=points)
        else:
            self.level += 1
            if self.aab_left:
                self.aab_left -= 1
            added = False
            if not self.aab_left:
                self.aab_count += 1
                self.aab_left = self.aab_count + 2
                if os_.multiball_start(os_.rom_balls_in_play() + 1, 312, 187):   # multiball_add_balls
                    self.restart_from_grace()
                    added = True
            self.mask = 7
            points = os_.score_add(200000)
            self.total += points
            more = 0 if added else self.aab_left
            # deff 60: points / BALL ADDED when argument 0x34 is 0, else points / %u MORE FOR / ADD-A-BALL
            # (the points on either screen's row: rom_layout.SCREENS)
            os_.deff_start(60, value=points, value_row2=points, more=more, screen=0 if more == 0 else 1)
            self.switch_value = min(self.switch_value + 1000, 50000)
        os_.request_refresh()
        return True

    # ------------------------------------------------------------------ end

    def restart_from_grace(self):
        """eol_restart_from_grace 0x010050b8: an add-a-ball in the grace restarts the mode."""
        os_ = self.os
        if os_.task_kill(GRACE_A) | os_.task_kill(GRACE_B):
            os_.flag_set(RUNNING)
            os_.request_refresh()

    def multiball_end(self):
        """eol_down_to_one_ball 0x01005154: flag 0x27 off, 187 + 125 ticks of grace, then the total."""
        os_ = self.os
        if not os_.flag(RUNNING):
            return
        os_.flag_clear(RUNNING)
        os_.task_start(GRACE_A, 187, self.grace_b)
        os_.request_refresh()

    def grace_b(self):
        self.os.task_start(GRACE_B, 125, self.grace_over)
        self.os.request_refresh()

    def grace_over(self):
        self.os.request_refresh()
        self.show_total()

    def show_total(self):
        """eol_show_total 0x01006240: task 0x4f shows deff 61 once the display is idle."""
        os_ = self.os
        if os_.state & 0x310 or not self.total:
            return False
        self.total_pending = True
        os_.display.when_idle(TOTAL_TASK, 61, on_end=self.total_done, value=self.total)
        return True

    def total_done(self):
        self.total_pending = False

    def ball_end(self):
        """eol_end_of_ball 0x01005124 (event 0x1d)."""
        os_ = self.os
        if self.active():
            os_.flag_clear(RUNNING)
            os_.task_kill(GRACE_A)
            os_.task_kill(GRACE_B)
            self.show_total()

    def ball_end_wait(self):
        return TOTAL_WAIT_TICKS if self.total_pending else None

    # ------------------------------------------------------------------ End of Line combo jackpot

    def eol_combo_jackpot_light(self):
        """eol_combo_jackpot_light 0x0100396c (right ramp): collectable for 156 + 93 ticks."""
        os_ = self.os
        os_.task_kill(COMBO_JACKPOT_LIT_B)
        os_.task_start(COMBO_JACKPOT_LIT_A, 156, self._combo_jackpot_lit_b)
        return True

    def _combo_jackpot_lit_b(self):
        self.os.task_start(COMBO_JACKPOT_LIT_B, 93)
        self.os.request_refresh()

    def eol_combo_jackpot(self):
        """eol_combo_jackpot_collect 0x010039e0 (VUK): score the jackpot, deff 139 (show task 0x87)."""
        os_, pd = self.os, self.pd
        if not (os_.task_running(COMBO_JACKPOT_LIT_A) or os_.task_running(COMBO_JACKPOT_LIT_B)):
            return False
        points = os_.score_add(pd.eol_combo_jackpot)
        os_.show(COMBO_JACKPOT_SHOW, 139, value=points)
        pd.eol_jackpot_collected = min(pd.eol_jackpot_collected + 1, 0xff)
        os_.task_kill(COMBO_JACKPOT_LIT_A)
        os_.task_kill(COMBO_JACKPOT_LIT_B)
        os_.request_refresh()
        return True


feature = EndOfLine
