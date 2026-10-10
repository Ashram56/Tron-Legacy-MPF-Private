"""Display effect (deff) manager: priorities, the background score display and the show queue.

Model of the SAM OS deff system as the Tron rules use it:
- Background deffs (event_map.csv background_loop = yes, e.g. 19 score display, 21 tilt) loop until
  replaced. Deff 19 starts ramp tube show 10 with it.
- Foreground deffs run for their recorded length (timing.json run_seconds) unless started with
  hold=True (the caller stops them, e.g. the bonus). A deff with a lower priority than the running
  foreground deff is not shown.
- What a deff starts by itself comes from the asset package (media_table): its lamp-matrix effects
  at once, its sounds at their offsets (logged with in_deff = the deff).
- A foreground deff spends its last 10 ticks in a hold at priority 0x20 (deff_hold_frames): any deff
  can replace it then.
- Show queue, queue_fullscreen_deff [0x0100fbb0]: "show" tasks (ids 0x81-0xa7) first run once their
  caller has finished, wait until the running deff's priority is below their threshold (0x9f for every
  caller) and they are the oldest show task waiting, then play their deff until its hold. While a show
  task runs, mode clocks pause and the VUK holds its ball.
- Mode TOTAL tasks (when_idle, FUN_0100fd88) wait for no show and no foreground deff.
- After an effect ends, and after a show ends, the deff rules re-assert the background deff (deff rule
  0x000198a8): deff 19, or the deff of the true mode rule, restarts in the background during normal play.
- Mode deff rules (lamp_rule_init list 2, os.deff_rule -> add_rule): on each rules refresh the true rule
  with the highest priority starts its background deff (even behind a show) when it changed, and its
  music call when that music is not already playing. With no mode rule true the score display rule runs
  with os.base_music() (0x01a before the playfield is valid, then 0x01b; 0x029 while Disc Battle is lit)
  [0x0100f594 / 0x0100f5c8]. Every start of a rule's deff is traced with rule=1 (ROM caller 0x19944).
- A few deffs hold for 1 tick only (HOLD_TICKS_BY_DEFF). A deff's exit handler stops the ramp tube show
  it started.
"""
import csv
import os

from tron import media_table

SHOW_THRESHOLD = 0x9f
SHOW_TIMEOUT = 0xea6
HOLD_TICKS = 10             # deffs end with deff_hold_frames(10, 0x20): priority 0x20 for the last 10 ticks
HOLD_PRIORITY = 0x20
# a few deffs hold for fewer ticks (read from their code: deff_hold_frames(1, 0x20))
HOLD_TICKS_BY_DEFF = {76: 1, 78: 1, 94: 1}
PREVALID_PRIO = 0x10        # priority of the score display rule that runs until the playfield is valid


class Show:
    __slots__ = ("task_id", "deff_id", "threshold", "timeout", "on_start", "on_end", "queued_at", "deff_args")

    def __init__(self, task_id, deff_id, threshold, timeout, on_start, on_end, queued_at, deff_args):
        self.task_id, self.deff_id, self.threshold, self.timeout = task_id, deff_id, threshold, timeout
        self.on_start, self.on_end, self.queued_at, self.deff_args = on_start, on_end, queued_at, deff_args


class Display:

    def __init__(self, os_):
        self.os = os_
        assets = os.path.join(os_.machine.machine_path, "..", "assets")
        self.media = media_table.load(assets)
        self.prio, self.background = {}, set()
        with open(os.path.join(assets, "mpf_package", "event_map.csv"), encoding="utf-8") as f:
            for row in csv.DictReader(f):
                deff_id = int(row["deff"])
                self.prio[deff_id] = int(row["priority"] or 0)
                if row["background_loop"] == "yes":
                    self.background.add(deff_id)
        self.fg = None              # running foreground deff id
        self.show_held = False      # a show ended in this deff's hold: its rules refresh is due at its exit
        self.arcade_held = False    # ... the Flynn's Arcade show 0x97: the score display comes back at its exit
        self.fg_prio = 0            # its priority (HOLD_PRIORITY in its last 10 ticks)
        self.fg_handle = None
        self.bg = None              # running background deff id
        self.shows = []             # waiting Show entries
        self.show = None            # Show playing now
        self._sound_handles = []
        self._pump_handle = None
        self.idle_waits = []        # [task_id, deff_id, deadline, on_end, deff_args] (when_idle)
        # Background deff rules (lamp_rule_init list 2, os.deff_rule): (priority, cond, deff, music, on_start).
        # The true rule with the highest priority owns the background deff and the music; without one, the
        # score display (deff 19) runs with the OS base music (os.base_music()).
        self.rules = []
        self.hold_tail = {}         # deff id -> seconds of its hold when not HOLD_TICKS (set_hold_tail)
        self.music = None           # music call the background rules last played

    # ------------------------------------------------------------------ start / stop

    def start(self, deff_id, hold=False, refresh=True, run_seconds=None, sounds=None, media=False, **args):
        """run_seconds: the run length when this call's variant differs from the recorded one.
        media: a held deff still plays its own sounds and lamp effects (deff 4, which runs until stopped).
        sounds: [(offset s, fn)] the deff's own sound calls when the rules make them (snd_play2 with an
        argument, a counter), played instead of the capture's sounds once the deff gets the display."""
        os_ = self.os
        os_.shaker_deff(deff_id)        # the deffs that run the shaker (shaker_run in the deff function)
        if deff_id in self.background:
            if self.bg not in (None, deff_id):
                os_.media.deff_stop(self.bg)
            self.bg = deff_id
            if self.is_rule_deff(deff_id):
                os_.trace.log("deff_start", id=deff_id, rule=1)   # a deff rule's deff (ROM caller 0x19944)
            else:
                os_.trace.log("deff_start", id=deff_id)
            os_.machine.events.post("tron_deff_{}".format(deff_id), **args)
            os_.media.deff_start(deff_id, self.prio.get(deff_id, 0), **args)
            if deff_id == 19:
                os_.tube_start(10)
            return True
        os_.trace.log("deff_start", id=deff_id)    # the ROM trace logs every start call
        if self.fg is not None and self.fg_prio > self.prio.get(deff_id, 0):
            # a higher priority deff keeps the display; the deff rules still run and restart a mode's
            # background deff (traces/disc_multiball.jsonl: deff 48 refused behind deff 50, deff 47 again)
            if refresh and not self.show and self.mode_bg():
                os_.after(1, lambda: self.mode_bg() and self.start(self.mode_bg(), refresh=False))
            return False
        self._end_fg(stopped=True)
        if self.bg is not None:
            os_.media.deff_stop(self.bg)
        self.fg = deff_id
        self.fg_prio = self.prio.get(deff_id, 0)
        self.bg = None
        os_.machine.events.post("tron_deff_{}".format(deff_id), **args)
        os_.media.deff_start(deff_id, self.prio.get(deff_id, 0), **args)
        info = self.media.get(deff_id)
        if info:
            seconds = run_seconds or info.seconds
            forced = os_.forced.get("deff_{}_seconds".format(deff_id))
            if forced:
                seconds = forced.pop(0) or seconds   # random length (e.g. the arcade reel), from a test
            if not hold or media:
                # the deff's own code starts its media once it runs: nothing if it is replaced at once
                self._sound_handles.append(os_.machine.clock.schedule_once(
                    lambda: self._media(deff_id, seconds, sounds), 0))
            if not hold and seconds:
                self.fg_handle = os_.machine.clock.schedule_once(lambda: self._ended(deff_id), seconds)
                from tron.os_layer import TICK
                hold_ticks = HOLD_TICKS_BY_DEFF.get(deff_id, HOLD_TICKS)
                self._sound_handles.append(os_.machine.clock.schedule_once(
                    lambda: self._hold(deff_id),
                    max(0.0, seconds - self.hold_tail.get(deff_id, hold_ticks * TICK))))
        if refresh and not self.show:
            os_.after(1, self.refresh)
        return True

    def _media(self, deff_id, seconds=None, sounds=None):
        """The deff's lamp effects, sounds and tube shows at their offsets. A capture can hold more than
        one run of the effect (deff 115 recorded two skipped stages back to back: 0x109 at 0 and 3.1 s);
        only what falls inside this run's length plays."""
        if self.fg != deff_id:
            return
        os_ = self.os
        info = self.media[deff_id]
        for leff in info.leffs:
            os_.leff_start(leff)
        if sounds is not None:
            events = [(t, "call", fn) for t, fn in sounds]
        else:
            events = [(t, "sound", c) for t, c in info.sounds if not seconds or t < seconds]
        events += [(t, "tube", n) for t, n in info.tubes if not seconds or t < seconds]
        for offset, kind, value in sorted(events, key=lambda e: e[0]):
            fire = (lambda k, v: lambda: self.fg == deff_id and (
                self._deff_sound(v, deff_id) if k == "sound" else v() if k == "call" else os_.tube_start(v)))(
                kind, value)
            if offset <= 0:
                fire()
            else:
                self._sound_handles.append(os_.machine.clock.schedule_once(fire, offset))

    def _hold(self, deff_id):
        """Last 10 ticks of deff_id (cancelled with it when it is replaced): its priority drops to 0x20,
        so any deff can replace it, and a show task (waiting for priority < 0x21) ends here
        [queue_fullscreen_deff 0x0100fbb0]; its rules pass restarts a mode's background deff behind the
        held deff (traces/end_of_line_multiball.jsonl: deff 57 at the hold of deff 56 and at its end)."""
        self.fg_prio = HOLD_PRIORITY
        if not self.show and deff_id in self.hold_tail:
            # a measured hold (set_hold_tail): its rules pass restarts the mode's background deff behind
            # it (traces/quorra_multiball: deff 65 again 2.78 s into deff 68)
            if self.os.in_play and self.bg not in (None, 19):
                self.start(self.bg, refresh=False)
            self.os.request_refresh()
        if self.show:
            # the show's rules refresh request is served once the deff exits (traces/gem_hurryup.jsonl:
            # one tube 18 start as deff 76 ends; disc_multiball.jsonl 40.03 s: one tube 43 as deff 48
            # ends), except for the Flynn's Arcade show 0x97, whose end the deferred rules wait for
            # (FUN_0100f164; clu_hurryup.jsonl 42.89 s: the music 0x01b as the reel's hold starts)
            if self.show.task_id == 0x97:
                self.os.request_refresh()
                self.arcade_held = True
            else:
                self.show_held = True
            show, self.show = self.show, None
            if show.on_end:
                show.on_end()
            deff_id, _, on_start = self.select()
            if self.os.in_play and deff_id != 19:
                self._start_rule(deff_id, on_start)
            self._pump()

    def stop(self, deff_id):
        os_ = self.os
        os_.trace.log("deff_stop", id=deff_id)
        os_.machine.events.post("tron_deff_{}_stop".format(deff_id))
        if self.fg == deff_id:
            self._end_fg(stopped=True)
            self._after_fg()
        elif self.bg == deff_id:
            self.bg = None
            if self.fg is None:
                self.refresh()                     # the rules' background deff comes back (deff 19)

    def set_hold_tail(self, deff_id, seconds):
        """deff_hold_frames(n, 0x20) [0x01024460] when a deff's hold is not the usual 10 ticks: for its last
        `seconds` the deff runs at priority 0x20, so any other deff may replace it (measured per deff)."""
        self.hold_tail[deff_id] = seconds

    def _deff_sound(self, call, deff_id):
        """A deff's own sound. When it is a mode rule's music call (intro deff 64 plays the Quorra music
        0x066), that music is playing, so the rule does not start it again (traces/quorra_multiball)."""
        self.os.sound(call, in_deff=deff_id)
        if any((r[3]() if callable(r[3]) else r[3]) == call for r in self.rules):
            self.music = call
        return True

    def queued(self, task_id):
        """Show task task_id is waiting in the queue (not playing yet)."""
        return any(s.task_id == task_id for s in self.shows)

    def extend(self, deff_id):
        """A running deff that takes new values (e.g. deff 43 on every pop hit) shows its full length again."""
        info = self.media.get(deff_id)
        if self.fg != deff_id or not self.fg_handle or not info or not info.seconds:
            return False
        self.os.machine.clock.unschedule(self.fg_handle)
        self.fg_handle = self.os.machine.clock.schedule_once(lambda: self._ended(deff_id), info.seconds)
        return True

    def running(self, deff_id):
        return deff_id in (self.fg, self.bg)

    def _end_fg(self, stopped=False, exit_handler=True):
        info = self.media.get(self.fg) if self.fg is not None else None
        if info:
            for leff in info.leffs:                # the deff's exit handler stops its lamp effects
                if self.os.leffs.is_running(leff):
                    self.os.leff_stop(leff)
        if self.fg_handle:
            self.os.machine.clock.unschedule(self.fg_handle)
            self.fg_handle = None
        for handle in self._sound_handles:
            self.os.machine.clock.unschedule(handle)
        self._sound_handles = []
        if self.fg is not None:
            self.os.media.deff_stop(self.fg)
        if self.show_held:
            self.show_held = False
            self.os.request_refresh()
        if exit_handler and info:
            # the deff's exit handler stops the ramp tube show it started (e.g. FUN_010022c4); no rules
            # refresh follows (traces/find_flynn_and_items.jsonl 18.15 s: tube 13 stops, no tube 14)
            for _, tube in info.tubes:
                if self.os.tubes.is_running(tube):
                    self.os.tubes.stop(tube)
        self.fg = None
        self.arcade_held = False

    def _ended(self, deff_id):
        self.fg_handle = None
        if self.fg != deff_id:
            return
        arcade_end = self.arcade_held
        self._end_fg()
        # the deff rules restart a mode's background deff when the effect in front of it ends
        # (traces/disc_multiball.jsonl: deff 47 again as deff 48/50 end)
        if self.mode_bg():
            self.start(self.mode_bg(), refresh=False)
            self.os.request_refresh()              # the same rules pass restarts the mode's tube show
        elif arcade_end:
            # the rules pass deferred during the Flynn's Arcade show 0x97 runs at its deff's exit and puts
            # the score display back (traces/flynns_arcade.jsonl 19.36 s: deff 19 as deff 105 ends); without
            # it the screen stayed empty until the next effect
            self.refresh()
        self._after_fg()

    def _after_fg(self):
        if self.show:
            self._end_show()
        self._pump()
        if self.fg is None and self.bg is None:
            # nothing left on the display: the deff rules [0x000198a8] put the background deff back (the
            # score display, or the mode's), as after every effect (traces/flynns_arcade.jsonl 19.36 s,
            # end_of_line_multiball.jsonl 38.60 s: deff 19 as the effect in front ends)
            self.refresh()

    def _end_show(self):
        show, self.show = self.show, None
        if show.on_end:
            show.on_end()
        self.refresh()
        self.os.request_refresh()                  # queue_fullscreen_deff: rules_refresh_request at the end

    def add_rule(self, cond, deff_id, music=None, priority=0, on_start=None):
        """lamp_rule_init(list 2): while cond() is true the background deff deff_id runs, with music
        (None/0 = keep; a callable gives the call, e.g. music by mode level). on_start() is called when
        the rule (re)starts the deff (the deff's own code)."""
        self.rules.append((priority, cond, deff_id, music, on_start))
        self.rules.sort(key=lambda r: -r[0])

    def raise_rule(self, deff_id):
        """A mode start re-inserts its rule before the others of its priority (e.g. FUN_0101ac74), so
        the mode started last shows its deff when several are true (stacked Light Cycle + Quorra)."""
        rule = next(r for r in self.rules if r[2] == deff_id)
        self.rules.remove(rule)
        i = next((k for k, r in enumerate(self.rules) if r[0] <= rule[0]), len(self.rules))
        self.rules.insert(i, rule)

    def is_rule_deff(self, deff_id):
        return any(r[2] == deff_id for r in self.rules)

    def select(self):
        """The true rule with the highest priority: (deff, music, on_start), else the score display."""
        valid = self.os.flag(0x1c) or self.os.pf_valid
        for prio, cond, deff_id, music, on_start in self.rules:
            if prio < PREVALID_PRIO and not valid:
                break                              # the score display rule before validation [0x0100f564]
            if cond():
                return deff_id, music() if callable(music) else music, on_start
        return 19, self.os.base_music(), None

    def _start_rule(self, deff_id, on_start):
        self.start(deff_id, refresh=False)
        if on_start:
            on_start()

    def refresh(self):
        """Deff rules [0x000198a8] after an effect ends: restart the background deff (deff 19 or a mode's)
        behind whatever runs, in normal play."""
        if self.os.in_play and self.bg is None and not self.show:
            deff_id, _, on_start = self.select()
            self._start_rule(deff_id, on_start)

    def mode_bg(self):
        """The mode background deff the rules select now (None: the score display)."""
        deff_id = self.select()[0] if self.os.in_play else 19
        return None if deff_id == 19 else deff_id

    def rules_refresh(self):
        """Rules refresh: a change of the selected rule starts its background deff and its music."""
        os_ = self.os
        if not os_.in_play:
            return
        deff_id, music, on_start = self.select()
        changed = deff_id != self.bg and (self.bg is not None or deff_id != 19)
        if changed:
            self._start_rule(deff_id, on_start)
        if music and music != self.music:
            if not changed and deff_id == 19:
                self.start(19, refresh=False)       # the ROM restarts the score display with new music
            self.music = music
            os_.sound(music)

    def clear(self):
        """Ball end / game end: drop the queue and the foreground deff (no trace event)."""
        self.shows = []
        self.show = None
        self.music = None
        self.idle_waits = []
        self._end_fg(exit_handler=False)
        if self._pump_handle:
            self.os.machine.clock.unschedule(self._pump_handle)
            self._pump_handle = None

    # ------------------------------------------------------------------ mode totals (tasks 0x4d-0x58)

    def when_idle(self, task_id, deff_id, timeout=SHOW_TIMEOUT, on_end=None, **deff_args):
        """FUN_0100fd88, used by the mode TOTAL tasks 0x4d-0x58: wait until no show task runs, no
        foreground deff is on screen and this is the oldest such task waiting, then play deff_id;
        on_end() runs when it is over (or when the wait times out)."""
        from tron.os_layer import TICK
        self.idle_waits = [w for w in self.idle_waits if w[0] != task_id]
        self.idle_waits.append([task_id, deff_id, self.os.now + timeout * TICK, on_end, deff_args])
        if len(self.idle_waits) == 1:
            self._idle_tick()

    def _idle_tick(self):
        from tron.os_layer import TICK
        now = self.os.now
        for w in [w for w in self.idle_waits if now > w[2]]:
            self.idle_waits.remove(w)
            if w[3]:
                w[3]()
        if not self.idle_waits:
            return
        if self.fg is None and not self.show_running():
            task_id, deff_id, _, on_end, args = self.idle_waits.pop(0)
            self.start(deff_id, **args)
            info = self.media.get(deff_id)
            if on_end:
                self.os.machine.clock.schedule_once(lambda: on_end(), info.seconds if info else 0)
        if self.idle_waits:
            self.os.machine.clock.schedule_once(self._idle_tick, TICK)

    # ------------------------------------------------------------------ show queue

    def queue(self, task_id, deff_id, timeout=SHOW_TIMEOUT, threshold=SHOW_THRESHOLD, on_start=None,
              on_end=None, **deff_args):
        self.shows = [s for s in self.shows if s.task_id != task_id]
        self.shows.append(Show(task_id, deff_id, threshold, timeout, on_start, on_end, self.os.now, deff_args))
        # FUN_0000c2b8 takes the first show task in the OS task list, i.e. the oldest one waiting
        # (traces/end_of_line_multiball.jsonl: task 0x87 deff 139, then 0x83 deff 133, then 0x97).
        # The show task first runs once its caller has finished (a deff the caller starts right after
        # queueing, e.g. deff 55 after the extra ball show 0x82, is on screen first).
        if self._pump_handle is None and not self.show:
            self._pump_handle = self.os.machine.clock.schedule_once(self._pump_tick, 0)

    def cancel(self, task_id):
        self.shows = [s for s in self.shows if s.task_id != task_id]

    def task_running(self, task_id):
        """task_running(id) for a show task: waiting in the queue or playing."""
        return bool(self.show and self.show.task_id == task_id) or any(s.task_id == task_id for s in self.shows)

    def show_running(self):
        """task_running_range(0x81, 0xa7): a show task is waiting or playing."""
        return bool(self.show or self.shows)

    def _pump(self):
        if self._pump_handle:
            self.os.machine.clock.unschedule(self._pump_handle)
            self._pump_handle = None
        if self.show or not self.shows:
            return
        from tron.os_layer import TICK
        now = self.os.now
        self.shows = [s for s in self.shows if now - s.queued_at <= s.timeout * TICK]
        if not self.shows:
            return
        first = self.shows[0]
        if self.fg is None or self.fg_prio < first.threshold:
            self.shows.pop(0)
            self.show = first
            self.start(first.deff_id, refresh=False, **first.deff_args)
            if first.on_start:
                first.on_start()
            self.os.request_refresh()            # rules that wait for this show's deff (e.g. a mode intro)
            if self.fg is None:                  # deff without a recorded length
                self._after_fg()
            return
        self._pump_handle = self.os.machine.clock.schedule_once(self._pump_tick, TICK)

    def _pump_tick(self):
        self._pump_handle = None
        self._pump()


class Tubes:
    """Ramp light tube shows (tube_show_start 0x0101b824, table 0x040e3c88 via io/light_effects.csv).

    Each show owns the left, right or both tubes with a priority. A start is refused when a show of
    the same or higher priority owns one of its tubes; otherwise it takes the tubes from lower shows
    (they stop). "once" shows end after their length, "loop"/"hold" shows run until stopped, and shows
    with no tube output end at once.
    """
    MASK = {"left": 1, "right": 2, "both": 3}

    def __init__(self, os_):
        self.os = os_
        self.info = {}
        path = os.path.join(os_.machine.machine_path, "..", "assets", "io", "light_effects.csv")
        with open(path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                length = float(row["length_ms"] or 0) / 1000
                # shows with no tube output in emulation still hold their tubes (traces: tube 13/14)
                kind = row["kind"] if row["kind"] in ("loop", "hold", "once") else "hold"
                self.info[int(row["leff"])] = (self.MASK.get(row["tubes"], 3), int(row["priority"] or 0), kind, length)
        self.running = {}           # show id -> end handle (or None)

    def is_running(self, show_id):
        return show_id in self.running

    def start(self, show_id):
        os_ = self.os
        os_.trace.log("tube_show_start", id=show_id)
        os_.machine.events.post("tron_tube_{}".format(show_id))
        mask, prio, kind, length = self.info.get(show_id, (3, 0, "loop", 0))
        losers = []
        for other in list(self.running):
            o_mask, o_prio = self.info.get(other, (3, 0, "", 0))[:2]
            if other == show_id or not o_mask & mask:
                continue
            if o_prio >= prio:
                return False
            losers.append(other)
        for other in losers:
            self.stop(other)
        self.stop(show_id, log=False)
        handle = None
        if kind == "once" and length:
            handle = os_.machine.clock.schedule_once(lambda: self._ended(show_id), length)
        self.running[show_id] = handle
        os_.lamps.tube_play(show_id)                # the show on the two RGB tube lights (lamps.py)
        return True

    def _ended(self, show_id):
        self.running.pop(show_id, None)
        self.os.lamps.tube_end(show_id)
        self.os.request_refresh()

    def stop(self, show_id, log=True):
        handle = self.running.pop(show_id, "absent")
        if handle != "absent" and handle:
            self.os.machine.clock.unschedule(handle)
        if handle != "absent":
            self.os.lamps.tube_end(show_id)
        if log and handle != "absent":
            self.os.trace.log("tube_show_stop", id=show_id)
            self.os.machine.events.post("tron_tube_{}_stop".format(show_id))

    def clear(self):
        for show_id in list(self.running):
            self.stop(show_id)


UNCLAIMED = {76}     # leff_076 [0x01006660] pulses the red/blue disc flasher itself (coil_pulse), no coil group


class Leffs:
    """Flasher ownership of lamp-matrix effects (assets/mpf_package/lamp_effects.csv: flashers, priority).

    Lamps are drawn in priority layers, so they never conflict (leff 99 starts under leff 52), but a
    leff start is refused while a running leff with a higher priority uses one of its flashers (a
    running lower one keeps running). When an effect ends or stops, the lamp rules start a refused rule
    leff that can run now (logged again; traces/recognizer_and_disc_battle.jsonl: leff 107 behind leff
    108; disc_multiball_restart.jsonl: leff 54 behind leff 52). Rule leffs run until the rule stops them.
    """

    def __init__(self, os_):
        self.os = os_
        self.info = {}
        path = os.path.join(os_.machine.machine_path, "..", "assets", "mpf_package", "lamp_effects.csv")
        with open(path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                outputs = frozenset(row["flashers"].split()) if int(row["leff"]) not in UNCLAIMED else frozenset()
                length = float(row["length_ms"]) / 1000 if row["loops"] == "0" and row["length_ms"] else None
                self.info[int(row["leff"])] = (outputs, int(row["priority"] or 0), length)
        self.running = {}           # leff id -> end handle (or None)
        self.pending = []           # refused lamp-rule leffs, started when an effect ends

    def is_running(self, leff_id):
        return leff_id in self.running

    def blocked(self, leff_id):
        outputs, prio, _ = self.info.get(leff_id, (frozenset(), 0, None))
        return any(other != leff_id and o_out & outputs and o_prio > prio
                   for other in self.running for o_out, o_prio, _ in (self.info.get(other, (frozenset(), 0, None)),))

    def flasher_outranked(self, leff_id, flasher):
        """A running leff with a higher priority than `leff_id` uses `flasher` (lamp_effects.csv)."""
        prio = self.info.get(leff_id, (frozenset(), 0, None))[1]
        return any(other != leff_id and flasher in self.info.get(other, (frozenset(), 0, None))[0]
                   and self.info[other][1] > prio for other in self.running)

    def start(self, leff_id, loop=False, lamp=None):
        """lamp: the lamp(s) a token effect draws (tron.lamps: the show's "(lamp)" token)."""
        if self.blocked(leff_id):
            if loop and leff_id not in self.pending:
                self.pending.append(leff_id)
            return False
        self.stop(leff_id)
        length = self.info.get(leff_id, (None, None, None))[2]
        handle = None
        if length and not loop and leff_id not in self.os.lamps.code_leffs:   # a code leff ends itself
            handle = self.os.machine.clock.schedule_once(lambda: self._ended(leff_id), length)
        self.running[leff_id] = handle
        self.os.lamps.leff_play(leff_id, lamp)      # its captured lamp show, on a layer at its priority
        return True

    def _ended(self, leff_id):
        self.running.pop(leff_id, None)
        self.os.lamps.leff_end(leff_id)
        self._retry()

    def _retry(self):
        """Outputs were freed: the lamp rules run again and start a refused rule leff that can run now."""
        if any(not self.blocked(p) for p in self.pending):
            from tron.os_layer import TICK
            self.os.machine.clock.schedule_once(lambda: self.os.rules_refresh(leffs_only=True), TICK / 2)

    def kill_all(self):
        """Every leff task killed with the other tasks (game start): no leff_stop is logged."""
        for handle in self.running.values():
            if handle:
                self.os.machine.clock.unschedule(handle)
        self.running.clear()
        self.pending = []
        self.os.lamps.leff_lamps_end()

    def retry_due(self, leff_id):
        return leff_id in self.pending and not self.blocked(leff_id)

    def stop(self, leff_id):
        if leff_id in self.pending:
            self.pending.remove(leff_id)
        if leff_id not in self.running:
            return
        handle = self.running.pop(leff_id)
        if handle:
            self.os.machine.clock.unschedule(handle)
        self.os.lamps.leff_end(leff_id)
        self._retry()
