"""Run a tron_ref reference scenario (assets/rules/traces/<name>.txt) against the MPF rebuild.

The scenario language is documented in assets/rules/tools/trace/README.md. The ball simulation is
MPF's smart_virtual platform: coil pulses move balls between devices, and this runner plays the
part of the player (plunge, drain, hits).

Usage: .venv/bin/python -m tests.scenario <name> [out.jsonl]
"""
import os
import shlex
import sys
import unittest

from tests.tron_test import ROOT, TronTestCase

TRACES = os.path.join(ROOT, "assets", "rules", "traces")
OUT = os.path.join(ROOT, "captures", "traces")

SCRIPT_START_TIME = 2.745 - 1.896   # 'start' runs this long after the Start press (reference traces)
# the reference traces credit a coin 0.528 s after the script starts; the coin task waits adj 62 COIN INPUT
# DELAY (30 ticks at factory settings) first, so the coin switch closes that much earlier, and START comes
# 0.144 s after the credit
COIN_DELAY = 30 * 0.01626
COIN_FIRST, COIN_GAP, START_AFTER_COIN = 0.528 - COIN_DELAY, 0.612, 0.144 + COIN_DELAY
# every hit is followed by 100 ms settle; with STEP_OVERSHOOT on both phases a hit lasts ~173 ms past
# its ms (reference traces: hit + wait 1 = 1.17-1.18 s)
SETTLE = 0.1
TROUGH_SWITCHES = (18, 19, 20, 21)  # tron_ref's 4-ball trough
VUK_HIT = 0.05                      # tron_ref closes sw11 for 50 ms (whatever ms says), then settles
# tron_ref's step_to() runs the emulator in 5 ms slices and stops at the first slice past the target, so
# each switch phase of a hit lasts about 6.5 ms longer (fit over the reference traces; plain waits do not
# drift: clu_hurryup's 51 waits stay on time).
STEP_OVERSHOOT = 0.00655
BUTTONS = {"left": "s_left_flipper", "right": "s_right_flipper", "tilt": "s_plumb_bob_tilt",
           "start": "s_start_button", "tournament": "s_tournament_start",
           # the coin door (states_ref's `button` names; coindoor -1 opens the door, 0 closes it)
           "back": "s_service_back", "minus": "s_service_minus", "plus": "s_service_plus",
           "select": "s_service_select", "slam": "s_slam_tilt", "coindoor": "s_coin_door_open", "coin": "s_coin"}


def switch_name(num):
    from tron.switches import SW
    return SW[int(num)]


def forced_picks(name):
    """Random choices the ROM made in the reference run, so the rebuild makes the same ones."""
    import json
    forced = {"arcade": []}
    path = os.path.join(TRACES, name + ".jsonl")
    if not os.path.exists(path):
        return forced
    evs = [json.loads(line) for line in open(path, encoding="utf-8")]
    for i, e in enumerate(evs):
        if e.get("ev") == "audit" and 0x53 <= e.get("id", 0) <= 0x5e:
            forced["arcade"].append(e["id"] - 0x53)
        if e.get("ev") == "deff_start" and e.get("id") == 38:
            hits = [n for n in evs[i + 1:] if n.get("ev") == "audit" and n.get("id") == 0x0f
                    and n["t"] - e["t"] < 7.5]
            forced.setdefault("match", []).append(len(hits))
        if e.get("ev") == "deff_start" and e.get("id") == 105:
            # the reel stops at a random slot: take the length from what followed the deff in the ROM.
            # That is the start of its 10-tick hold (deff_hold_frames(10, 0x20)), where the next deff may
            # start, so the run length is 10 ticks longer.
            hold = 10 * 0.01626
            # the slot the award stopped in: the reel scrolls 5, 18 or 30 frames of 3 ticks before its
            # stop sound 0x0e3 (deff_105_arcade_award 0x0100e8bc)
            stop = next((n["t"] - e["t"] for n in evs[i + 1:] if n.get("ev") == "sound"
                         and n.get("call") == "0x0e3" and n.get("in_deff") == 105), None)
            if stop is not None:
                from tron.features.arcade import scroll_frames
                forced.setdefault("arcade_slot", []).append(
                    min(range(3), key=lambda k: abs(scroll_frames(k) * 3 * 0.01626 - stop)))
            for n in evs[i + 1:]:
                if n.get("ev") == "deff_start" and n.get("id") not in (19, 105):
                    forced.setdefault("deff_105_seconds", []).append(n["t"] - e["t"] + hold)
                    break
                if n.get("ev") == "sound" and n.get("call") == "0x0fd":
                    forced.setdefault("deff_105_seconds", []).append(n["t"] - e["t"] - 0.045 + hold)
                    break
    # left outlane hits (task 0x37 starts, logged twice per hit): insult speech 0x129 or not
    lefts = sorted({e["t"] for e in evs if e.get("ev") == "task_start" and e.get("task") == "0x37"})
    forced["insult"] = [0 if any(n.get("ev") == "sound" and n.get("call") == "0x129" and 0 <= n["t"] - t < 0.1
                                 for n in evs) else 1 for t in lefts]
    for deff_id, (stop_ev, stop_id) in CLIP_DEFFS.items():
        forced["deff_{}_seconds".format(deff_id)] = clip_lengths(evs, deff_id, stop_ev, stop_id)
    forced.update(forced_samples(evs))
    return forced


def forced_samples(evs):
    """Sample picks of sound calls that a chained sound (snd_play_chain, caller 0x2ccb8) waited for: the
    gap from the call to the chained sound tells which sample the ROM played."""
    import csv
    base = os.path.join(ROOT, "assets", "callouts")
    dur = {}
    with open(os.path.join(base, "samples_index.csv"), encoding="utf-8") as f:
        for row in csv.DictReader(f):
            dur[int(row["sample_id"], 16)] = float(row["duration_s"] or 0)
    lengths = {}
    with open(os.path.join(base, "sound_calls.csv"), encoding="utf-8") as f:
        for row in csv.DictReader(f):
            lengths[int(row["call_id"], 16)] = [dur.get(int(x, 16), 0)
                                                for x in row["sample_ids (one picked per play)"].split()]
    sounds = [e for e in evs if e.get("ev") == "sound" and not e.get("in_deff")]
    picks, index = {}, {}
    for e in sounds:
        call = int(e["call"], 16)
        if e.get("caller") == "0x2ccb8":
            continue
        if len(lengths.get(call, [])) > 1:
            index[id(e)] = (call, len(picks.setdefault(call, [])))
            picks[call].append(None)
    for i, e in enumerate(sounds):
        if e.get("caller") != "0x2ccb8":
            continue
        for prev in reversed(sounds[:i]):
            if id(prev) not in index:
                continue
            call, n = index[id(prev)]
            gap = e["t"] - prev["t"]
            best = min(range(len(lengths[call])), key=lambda k: abs(lengths[call][k] - gap))
            if abs(lengths[call][best] - gap) < 0.05:
                picks[call][n] = best
                break
    return {"sample_0x{:03x}".format(c): p for c, p in picks.items() if any(x is not None for x in p)}


# Deffs that play a random film clip first, so their length varies: the ROM's length is read from the
# stop of the effect the deff runs (its exit handler stops it). A deff replaced by a new start of the
# same deff keeps the recorded length (None).
CLIP_DEFFS = {48: ("leff_stop", 48), 111: ("tube_show_stop", 62)}


def clip_lengths(evs, deff_id, stop_ev, stop_id):
    out = []
    for i, e in enumerate(evs):
        if e.get("ev") != "deff_start" or e["id"] != deff_id:
            continue
        length = None
        for n in evs[i + 1:]:
            if n["t"] < e["t"] + 0.005:
                continue                    # the previous run's effect stops as this one starts
            if n.get("ev") == "deff_start" and n["id"] == deff_id:
                break                       # replaced by its next start
            if n.get("ev") == stop_ev and n.get("id") == stop_id:
                length = n["t"] - e["t"]
                break
        out.append(length)
    return out


class ScenarioRun(TronTestCase):
    """One scenario per test instance; the scenario name comes from the environment."""

    scenario = None
    out_path = None
    FREE_PLAY = False                 # factory settings: the script's coins pay for the game

    def runTest(self):
        self.run_scenario(self.scenario, self.out_path)

    # ------------------------------------------------------------------ helpers

    def wait(self, seconds):
        self.advance_time_and_run(seconds)

    def sw(self, name, state):
        self.machine.switch_controller.process_switch(name, state, True)

    def log(self, ev, **kw):
        self.tron.trace.log(ev, **kw)

    def _on_shooter(self, **kwargs):
        if self.autoplunge > 0:
            self.machine.clock.schedule_once(self._auto_plunge, self.autoplunge)

    def _auto_plunge(self):
        if self.machine.switches["s_shooter_lane"].state:
            self.log("sim", what="plunged")
            self.sw("s_shooter_lane", 0)

    # ------------------------------------------------------------------ commands

    def run_scenario(self, name, out_path=None):
        os.makedirs(OUT, exist_ok=True)
        out_path = out_path or os.path.join(OUT, name + ".jsonl")
        trace = self.tron.trace
        trace.path = out_path
        trace._file = open(out_path, "w", encoding="utf-8")
        self.autoplunge = 1.0
        self.machine.switch_controller.add_switch_handler("s_shooter_lane", self._on_shooter, state=1)
        self.tron.forced = forced_picks(name)
        self.fill_trough()
        self.wait(6)                                  # the ROM boots 8 s before line 1
        self.log("ready")
        with open(os.path.join(TRACES, name + ".txt"), encoding="utf-8") as f:
            for line in f:
                line = line.split("#", 1)[0].strip()
                if line.startswith("mark "):
                    self.command(["mark", line[5:].strip()])     # free text (may hold quotes)
                elif line:
                    self.command(shlex.split(line))
        self.log("end")
        trace.close()
        return out_path

    def command(self, args):
        cmd, rest = args[0], args[1:]
        getattr(self, "cmd_" + cmd)(*rest)

    def cmd_start(self, n="1"):
        n = int(n)
        self.log("script", what="start", players=n)
        self.wait(COIN_FIRST)
        for i in range(3 * n):
            if i:
                self.wait(COIN_GAP)
            self.sw("s_coin", 1)
            self.wait(0.01)
            self.sw("s_coin", 0)
        self.wait(START_AFTER_COIN - 0.01)
        for _ in range(n):
            self.sw("s_start_button", 1)
            self.wait(0.01)
            self.sw("s_start_button", 0)
            self.wait(0.09)
        self.wait(SCRIPT_START_TIME - 0.1 * n)

    def step(self, seconds):
        """One tron_ref step_to(): the requested time plus the average overshoot."""
        self.wait(seconds + STEP_OVERSHOOT)

    def cmd_wait(self, s):
        self.wait(float(s))                            # plain waits do not drift (see STEP_OVERSHOOT)

    def cmd_hit(self, sw, ms="60"):
        name = switch_name(sw)
        self.log("switch", sw=int(sw))
        self.sw(name, 1 if int(sw) != 41 else 0)
        if int(sw) == 11:                             # the VUK holds the ball until coil 4 fires
            self.wait(VUK_HIT + STEP_OVERSHOOT)
            self.wait(SETTLE + STEP_OVERSHOOT)
            return
        self.wait(float(ms) / 1000 + STEP_OVERSHOOT)
        self.sw(name, 0 if int(sw) != 41 else 1)
        self.wait(SETTLE + STEP_OVERSHOOT)

    def cmd_hold(self, sw):
        self.log("switch_hold", sw=int(sw))
        if int(sw) in TROUGH_SWITCHES:              # a ball arriving in the trough is a drain
            self.cmd_drain()
            return
        self.sw(switch_name(sw), 1)

    def cmd_release(self, sw):
        self.log("switch_release", sw=int(sw))
        if int(sw) in TROUGH_SWITCHES:              # MPF's trough device owns its ball switches
            return
        self.sw(switch_name(sw), 0)

    def cmd_plunge(self):
        self._auto_plunge()

    def cmd_autoplunge(self, s="1"):
        self.autoplunge = float(s)

    def cmd_drain(self, side=None):
        if side:
            name = "s_left_outlane" if side == "left" else "s_right_outlane"
            self.log("switch", sw=24 if side == "left" else 29)
            self.sw(name, 1)
            self.step(0.06)                           # tron_ref pulses the outlane, then drains at once
            self.sw(name, 0)
        self.log("sim", what="drain")
        self.machine.default_platform.add_ball_to_device(self.machine.ball_devices["bd_trough"])
        self.step(0.1)

    def cmd_adj(self, num, value):
        self.tron.adj[int(num)] = int(value)

    def cmd_poke(self, addr, value, size="1"):
        self.tron.poke(int(addr, 16), int(value))

    def cmd_button(self, button, ms="100"):
        name = BUTTONS[button]
        ms = int(ms)
        self.log("button", button=button, ms=ms)
        if ms == 0:
            self.sw(name, 0)
        elif ms < 0:
            self.sw(name, 1)
        else:
            self.sw(name, 1)
            self.step(ms / 1000)
            self.sw(name, 0)
            self.step(0.05)                           # tron_ref: 50 ms settle after a button pulse

    def cmd_mark(self, *text):
        self.log("mark", text=" ".join(text))


def run(name, out_path=None):
    test = ScenarioRun()
    test.scenario, test.out_path = name, out_path
    result = unittest.TextTestRunner(verbosity=0).run(test)
    return result.wasSuccessful()


if __name__ == "__main__":
    ok = run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    sys.exit(0 if ok else 1)
