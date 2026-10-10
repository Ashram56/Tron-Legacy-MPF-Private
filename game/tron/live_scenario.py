"""Plays a tron_ref scenario (assets/rules/traces/<name>.txt) in real time on a running machine.

Used for live render checks with the Godot media controller: `TRON_LIVE_SCENARIO=<name> mpf game . -c config,hw_virtual -t -X`
(the smart_virtual platform moves the balls). The commands mirror tests/scenario.py, which runs the same
scripts in virtual time for the trace comparisons.
"""
import os
import shlex

# the reference traces credit a coin 0.528 s after the script starts; the coin task waits adj 62 COIN INPUT
# DELAY (30 ticks at factory settings) first, so the coin switch closes that much earlier, and START comes
# 0.144 s after the credit
COIN_DELAY = 30 * 0.01626
COIN_FIRST, COIN_GAP, START_AFTER_COIN = 0.528 - COIN_DELAY, 0.612, 0.144 + COIN_DELAY
SCRIPT_START_TIME = 2.745 - 1.896
SETTLE = 0.1
TROUGH_SWITCHES = (18, 19, 20, 21)  # tron_ref's 4-ball trough: MPF's trough device owns these switches
RANDOM_SEED = 1974                  # tests/tron_test.py; live play stays unseeded
BUTTONS = {"left": "s_left_flipper", "right": "s_right_flipper", "tilt": "s_plumb_bob_tilt",
           "start": "s_start_button", "tournament": "s_tournament_start",
           # the coin door (states_ref's `button` names; coindoor -1 opens the door, 0 closes it)
           "back": "s_service_back", "minus": "s_service_minus", "plus": "s_service_plus",
           "select": "s_service_select", "slam": "s_slam_tilt", "coindoor": "s_coin_door_open", "coin": "s_coin"}


class LiveScenario:

    def __init__(self, os_, name):
        self.os = os_
        self.machine = os_.machine
        self.name = name
        self.t = 0.0
        self.autoplunge = 1.0
        self.started = False
        self.machine.events.add_handler("mode_attract_started", self._start, priority=1)

    def _start(self, **kwargs):
        if self.started:
            return
        self.started = True
        self.os.random.seed(RANDOM_SEED)                # a scenario replays the same random choices
        self.machine.switch_controller.add_switch_handler("s_shooter_lane", self._on_shooter, state=1)
        path = self.name if self.name.endswith(".txt") else os.path.join(
            self.machine.machine_path, "..", "assets", "rules", "traces", self.name + ".txt")   # or a script file
        self.t = 2.0                                   # let the media controller settle
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.split("#", 1)[0].strip()
                if line.startswith("mark "):
                    self.cmd_mark(line[5:].strip())   # free text (may hold quotes), as tests/scenario.py
                elif line:
                    args = shlex.split(line)
                    getattr(self, "cmd_" + args[0])(*args[1:])
        self.at(0, lambda: self.os.trace.log("live_scenario_end"))

    # ------------------------------------------------------------------ helpers

    def at(self, delay, fn):
        self.machine.clock.schedule_once(lambda: fn(), self.t + delay)

    def sw(self, name, state, delay=0.0):
        self.at(delay, lambda: self.machine.switch_controller.process_switch(name, state, True))

    def _on_shooter(self, **kwargs):
        if self.autoplunge > 0:
            self.machine.clock.schedule_once(self._plunge, self.autoplunge)

    def _plunge(self):
        if self.machine.switches["s_shooter_lane"].state:
            self.machine.switch_controller.process_switch("s_shooter_lane", 0, True)

    # ------------------------------------------------------------------ commands

    def cmd_start(self, n="1"):
        n = int(n)
        t = COIN_FIRST
        for i in range(3 * n):
            if i:
                t += COIN_GAP
            self.sw("s_coin", 1, t)
            self.sw("s_coin", 0, t + 0.01)
        t += START_AFTER_COIN
        for _ in range(n):
            self.sw("s_start_button", 1, t)
            self.sw("s_start_button", 0, t + 0.01)
            t += 0.1
        self.t += t + SCRIPT_START_TIME - 0.1 * n

    def cmd_wait(self, s):
        self.t += float(s)

    def cmd_hit(self, sw, ms="60"):
        from tron.switches import SW
        name, num = SW[int(sw)], int(sw)
        self.sw(name, 1 if num != 41 else 0)
        if num != 11:
            self.sw(name, 0 if num != 41 else 1, float(ms) / 1000)
        self.t += float(ms) / 1000 + SETTLE

    def cmd_hold(self, sw):
        from tron.switches import SW
        if int(sw) in TROUGH_SWITCHES:              # a ball arriving in the trough is a drain (tests/scenario.py)
            self.cmd_drain()
            return
        self.sw(SW[int(sw)], 1)

    def cmd_release(self, sw):
        from tron.switches import SW
        if int(sw) in TROUGH_SWITCHES:
            return
        self.sw(SW[int(sw)], 0)

    def cmd_plunge(self):
        self.at(0, self._plunge)

    def cmd_autoplunge(self, s="1"):
        self.at(0, lambda: setattr(self, "autoplunge", float(s)))

    def cmd_drain(self, side=None):
        if side:
            name = "s_left_outlane" if side == "left" else "s_right_outlane"
            self.sw(name, 1)
            self.sw(name, 0, 0.06)
            self.t += 0.06 + SETTLE
        trough = self.machine.ball_devices["bd_trough"]
        self.at(0, lambda: self.machine.default_platform.add_ball_to_device(trough))
        self.t += 0.12

    def cmd_adj(self, num, value):
        self.at(0, lambda: self.os.adj.override(int(num), int(value)))     # not stored as the operator's

    def cmd_poke(self, addr, value, size="1"):
        self.at(0, lambda: self.os.poke(int(addr, 16), int(value)))

    def cmd_button(self, button, ms="100"):
        name, ms = BUTTONS[button], int(ms)
        if ms == 0:
            self.sw(name, 0)
        elif ms < 0:
            self.sw(name, 1)
        else:
            self.sw(name, 1)
            self.sw(name, 0, ms / 1000)

    def cmd_mark(self, *text):
        self.at(0, lambda: self.os.trace.log("mark", text=" ".join(text)))
