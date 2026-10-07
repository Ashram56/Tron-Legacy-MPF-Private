"""Sends the rules' display effects and sound calls to the Godot media controller (GMC) over BCP.

The OS layer reports every deff start/stop and sound call here. Slides and sounds come from
scripts/gen_media.py (game/slides/deffs, game/sounds, game/tron/media_data.json). Without that data
or without a connected GMC (unit tests), nothing is sent.

- deff N -> slide "deff_NNN" at the deff's ROM priority; text lines with values are formatted from
  the deff's ROM text (event_map.csv rom_text) and its arguments.
- sound call N -> one sample of pool N (sounds.yaml), on the call's track (voice, sfx, music). Music
  calls replace the running music. Calls 0x01-0x08 are the ROM's channel stops.
"""
import json
import os
import re

CONTEXT = "tron_media"
SERVICE_PRIORITY = 1000         # the service slide covers every deff (ROM priorities are 0-255)
TICK = 0.01626                                     # seconds per ROM tick (os_layer.TICK)
SPEC = re.compile(r"%(P\d/[^%]*%|[-+ #0,]*\d*l?[dus])")
# The values of a deff's printf lines, in the ROM's argument order, for effects whose callers also pass
# arguments the text does not print (the others: every argument not in the deff's "args", in call order).
# deff 55 (0x0100461c): before / after / flags pick the screen, only `more` is printed ("%u MORE TO").
# deff 138 (0x01003c30): "%u" combo count (ring font), "%,02lu" points, the named combo ("%s", blank when
# the shots match no named combo) and "JACKPOT=%,02lu"; the combo total is not shown. Without this the
# kwargs order printed the combo name where the points go: "WAY / COMBO / CASTOR".
# deff 43 (0x0101c65c): "%d MORE" pop hits left (RAM, live), "%,02lu" the points of the hit that started it,
# "%,02lu" the player's score (live); value / mult are not printed.
# deff 62 (0x0101d33c): only the loops still needed (task + 0x34) are printed, not the points.
# deffs 68 / 69 (0x0101e320 / 0x0101e654): the points on the row of the screen shown (`screen` = the double arg).
# deff 78 (0x0101476c): "%d FOLLOWING%P1//S/%" the award count (task + 0x34), then the points (+ 0x30).
# deff 140 (0x0102faec): the Sea of Simulation bonus (task + 0x34), not the start total.
TEXT_ARGS = {43: ("hits_left", "points", "score"), 55: ("more",), 62: ("left",),
             68: ("points", "points"), 69: ("points", "points"), 78: ("followings", "value"), 138: ("count", "points", "named", "jackpot"), 140: ("sos_bonus",)}


def format_rom_text(line, args):
    """printf as the ROM's text_printf_msg uses it: %d %u %s, %,02lu (score with commas),
    %P1/a/b/c/% (plural or ordinal pick by the previous number)."""
    args = list(args)
    last = [0]

    def sub(m):
        spec = m.group(1)
        if spec.startswith("P"):
            choices = spec[3:-1].split("/")
            n = last[0]
            if spec[1] == "1" and len(choices) > 2:     # ordinal list: 1-based
                return choices[n - 1] if 0 < n <= len(choices) else ""
            return choices[0] if n == 1 else (choices[2] if len(choices) > 2 else choices[-1])
        value = args.pop(0) if args else 0
        if value is None:
            return ""
        if spec.endswith("s"):
            return str(value)
        try:
            value = int(value)
        except (TypeError, ValueError):            # never print a name or a tuple where the ROM prints a number
            return ""
        last[0] = value
        text = "{:,}".format(value) if "," in spec else str(value)
        flags, width = re.match(r"([-+ #0,]*)(\d*)", spec).groups()
        if width:                                  # %,02lu: score 0 shows "00"; %06d zero-padded
            text = text.rjust(int(width), "0" if "0" in flags or width.startswith("0") else " ")
        return text
    return SPEC.sub(sub, line)


class MediaBridge:

    def __init__(self, os_):
        self.os = os_
        self.machine = os_.machine
        path = os.path.join(os.path.dirname(__file__), "media_data.json")
        self.data = None
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            self.data = {"pools": {int(k): v for k, v in data["pools"].items()},
                         "deffs": {int(k): v for k, v in data["deffs"].items()}}
        self.music_key = None
        self.service_shown = False
        self.counters = {}
        self.last_scores = {}
        self.award = (0, None, None)               # last points, shown since, blink counter since
        self.bar_max = {}
        self._refresh = None
        self.active = set()                        # deffs on screen that draw the status panel or live values
        self.started = {}                          # deff id -> the args of its last start
        # (deff, line, ROM text) of every printf line left blank because the rules gave no value for it
        # (tests/test_dmd_text.py: a value line drawn without its value shows a bare label, "RIGHT SPINNER =")
        self.missing = []
        # the DMD keeps its last frame while no effect draws (the ROM never clears it between effects): the
        # last deff / text slide stays up until the next one plays, never GMC's base slide below them all
        self.shown = set()                         # deff and text slides playing now
        self.kept = None                           # the last one, stopped but left up until the next plays
        self.drawn = set()                         # deffs shown by deff_draw (rom_screen) in place of their frames

    # ------------------------------------------------------------------ transport

    def connected(self, need_data=True):
        bcp = getattr(self.machine, "bcp", None)
        if (need_data and not self.data) or not bcp or not getattr(bcp, "transport", None):
            return False
        return bool(bcp.transport.get_named_client("local_display"))

    def _send(self, name, settings, priority=0, need_data=True, **kwargs):
        """Send a slides_play / sounds_play trigger straight to GMC. MPF's bcp_trigger() only reaches clients
        that registered a handler for the name, and GMC registers none for sounds_play (MPF's own
        sound_player config would): sent that way, every sound was dropped."""
        if not self.connected(need_data):
            return
        bcp = self.machine.bcp
        client = bcp.transport.get_named_client("local_display") if getattr(bcp, "transport", None) else None
        args = dict(name=name, settings=settings, context=CONTEXT, calling_context=CONTEXT, priority=priority,
                    **kwargs)
        if client:
            bcp.interface.bcp_trigger_client(client=client, **args)
        else:                                      # unit tests: a mocked interface, no transport client
            bcp.interface.bcp_trigger(**args)

    # ------------------------------------------------------------------ display effects

    def deff_lines(self, deff_id, args):
        info = self.data["deffs"].get(deff_id) if self.data else None
        if not info:
            return {}
        live = getattr(self.os, "deff_values", {}).get(deff_id)
        if live:                                       # values the deff reads from RAM, now (over the passed ones)
            args = dict(args, **live())
        passed = {k: args[k] for k in info.get("args", []) if k in args}   # e.g. letters for letter_panel.gd
        if not info["text"]:
            return dict(self.score_display_args() if info.get("panel") else {}, **passed)
        if deff_id in TEXT_ARGS:
            values = [args.get(k) for k in TEXT_ARGS[deff_id]]
        else:
            values = [v for k, v in args.items() if k not in info.get("args", [])]   # not lit/new/screen
        if deff_id == 19:                              # score display: ball number and score
            values = [self.machine.game.player.ball if self.os.game and self.os.game.player else 0,
                      self.os.game.player.score if self.os.game and self.os.game.player else 0]
        out = dict(self.score_display_args() if info.get("panel") else {}, **passed)
        for i, line in enumerate(info["text"]):
            n = sum(1 for spec in SPEC.findall(line) if not spec.startswith("P"))   # %P picks by the last number
            if n and len(values) < n:              # value not reported by the rules: leave the line blank
                out["line{}".format(i)] = ""
                self.missing.append((deff_id, i, line))
                values = []
                continue
            out["line{}".format(i)] = format_rom_text(line, values[:n])
            values = values[n:]
        return out

    def deff_start(self, deff_id, priority, **args):
        info = self.data["deffs"].get(deff_id) if self.data else None
        if not info:
            return
        slide = info["slide"]
        self.started[deff_id] = args
        if info.get("panel") or deff_id in getattr(self.os, "deff_values", {}):
            self.active.add(deff_id)
            if self._refresh is None and self.connected():   # timer bars move between scores
                self._refresh = self.machine.clock.schedule_interval(self.score_changed, 0.25)
        self._send("slides_play", {slide: {"action": "remove", "key": slide, "expire": None}})
        self._send("slides_play", {slide: {"action": "play", "key": slide, "expire": None,
                                           "priority": priority}},
                   priority=priority, **self.deff_lines(deff_id, args))
        self._played(slide)

    def deff_stop(self, deff_id):
        info = self.data["deffs"].get(deff_id) if self.data else None
        self.active.discard(deff_id)
        if deff_id in self.drawn:
            self.drawn.discard(deff_id)
            self._remove("rom_screen")
        elif info:
            self._remove(info["slide"])

    def deff_draw(self, deff_id, priority, draw):
        """A running deff whose next screen its captured frames do not hold (deff 4 dims after 30 s): the ROM
        draw list `draw` (tron/rom_draw.py) on the rom_screen slide (tron/service_screen.gd), in place of the
        deff's frames, until the deff stops."""
        info = self.data["deffs"].get(deff_id) if self.data else None
        if not info:
            return
        self.drawn.add(deff_id)
        self.text_show("rom_screen", [], priority, draw=draw)
        self.shown.discard(info["slide"])
        self._send("slides_play", {info["slide"]: {"action": "remove", "key": info["slide"], "expire": None}},
                   need_data=False)

    def _played(self, slide):
        self.shown.add(slide)
        kept, self.kept = self.kept, None
        if kept and kept != slide:
            self._send("slides_play", {kept: {"action": "remove", "key": kept, "expire": None}}, need_data=False)

    def _remove(self, slide):
        self.shown.discard(slide)
        if not self.shown:
            self.kept = slide                      # nothing else up: its last frame stays (see self.kept)
            return
        self._send("slides_play", {slide: {"action": "remove", "key": slide, "expire": None}}, need_data=False)

    # ------------------------------------------------------------------ score display (deff 19)

    def credits_text(self):
        """FUN_00004ff4: "FREE PLAY", "CREDITS n", "CREDITS a/b" (coins toward the next credit) or
        "CREDITS n a/b". The credit count comes from the OS when it keeps one (os.credits,
        os.credit_fraction = (coins, coins per credit), os.free_play); 3 coins make a credit."""
        if getattr(self.os, "free_play", False):
            return "FREE PLAY"
        whole = int(getattr(self.os, "credits", 0) or 0)
        num, den = getattr(self.os, "credit_fraction", None) or (getattr(self.os, "coins", 0) % 3, 3)
        if num == 0:
            return "CREDITS %d" % whole
        if whole == 0:
            return "CREDITS %d/%d" % (num, den)
        return "CREDITS %d %d/%d" % (whole, num, den)

    def replay_text(self):
        """FUN_01023704: the current player's first replay level not yet awarded ("REPLAY AT <level>",
        the award text for adj 13 = 0; the other awards' texts are ROM messages not in the package)."""
        level_of = getattr(self.os, "replay_level", None)
        if not level_of:
            return ""
        done = getattr(self.os, "replays_awarded", {}).get(self.os.player_num, set())
        for n in range(1, 5):
            level = level_of(n)
            if level and n not in done:
                return "REPLAY AT " + format_rom_text("%,02lu", [level])
        return ""

    def _bar(self, key, seconds, start=0):
        """Timer bar length 0-10: seconds * 10 / start (FUN_01022ffc keeps the larger of both)."""
        top = max(self.bar_max.get(key, 0) if seconds else 0, start, seconds)
        self.bar_max[key] = top
        return seconds * 10 // top if top else 0

    def score_display_args(self):
        """Event args of deff 19 beyond line0/line1, for tron/score_display.gd."""
        game = self.os.game
        players = game.player_list if game else []
        now = self.machine.clock.get_time()
        current = self.os.player_num
        if current and players:                      # last points: the current player's score change
            score = players[current - 1].score
            delta = score - self.last_scores.get(current, score)
            self.last_scores[current] = score
            value, shown, _ = self.award
            if delta > 0:
                age = (now - shown) / TICK if shown is not None else 99
                self.award = (value, shown, now) if age < 16 and delta < value else (delta, now, now)
        value, shown, blink = self.award
        out = {"players": max(len(players), 1), "player": current or 1,
               "valid": bool(getattr(self.os, "ball_validated", False)) or not game,
               "credits": self.credits_text(), "replay": self.replay_text() if game else "",
               "award": format_rom_text("%,02lu", [value]) if value else "",
               "award_age": int((now - shown) / TICK) if shown is not None else 99,
               "blink_age": int((now - blink) / TICK) if blink is not None else 999}
        for p in range(1, 5):
            out["p%d" % p] = format_rom_text("%,02lu", [players[p - 1].score]) if p <= len(players) else ""
        feats = self.os.features_by_name if hasattr(self.os, "features") else {}
        targets = feats.get("tron_targets")
        for bit, key in ((1, "bar_ds"), (2, "bar_bumpers"), (4, "bar_spinners")):
            secs = targets.secs.get(bit, 0) if targets else 0
            out[key] = self._bar(key, secs)
        for name, key in (("zuse", "bar_zfs"), ("clu", "bar_clu"), ("gem", "bar_gem")):
            clock = getattr(feats.get(name), "clock", None)
            out[key] = self._bar(key, clock.seconds if clock else 0)
        return out

    def score_changed(self, *_):
        """Score flush (and every 0.25 s while a panel shows): refresh the score display and the
        status panel of the effects on screen."""
        if not self.data:
            return
        args = None
        for deff_id in sorted(self.active | ({19} if self.os.display.bg == 19 else set())):
            info = self.data["deffs"].get(deff_id)
            live = deff_id in getattr(self.os, "deff_values", {})
            if not info or not (info.get("panel") or live):
                continue
            args = self.score_display_args() if args is None else args
            mine = dict(args) if info.get("panel") else {}
            if deff_id == 19 or live:
                # its own lines only: BALL n / score for deff 19, fresh RAM values for a live deff (one
                # effect's lines never go to another: they share the names line0, line1, ...)
                mine.update({k: v for k, v in self.deff_lines(deff_id, self.started.get(deff_id, {})).items()
                             if k.startswith("line") or k == "screen"})
            self._send("slides_play", {info["slide"]: {"action": "update", "key": info["slide"],
                                                       "expire": None}}, **mine)
        if args is None:
            self.score_display_args()                  # keep the last-points tracking current

    # ------------------------------------------------------------------ service menu

    def text_show(self, slide, lines, priority, **extra):
        """Rules text on a generic slide (game/slides/<slide>.tscn, labels line0-line2); needs no generated
        media: the service menu, the attract pages and the initials entry."""
        lines = {"line{}".format(i): text for i, text in enumerate(lines)}
        self._send("slides_play", {slide: {"action": "remove", "key": slide, "expire": None}}, need_data=False)
        self._send("slides_play", {slide: {"action": "play", "key": slide, "expire": None, "priority": priority}},
                   priority=priority, need_data=False, **lines, **extra)
        self._played(slide)

    def text_hide(self, slide):
        self._remove(slide)

    def service_show(self, lines, draw=None):
        """Service menu screen (tron/service.py), above every deff: the ROM draw list `draw` (tron/rom_draw.py,
        drawn by tron/service_screen.gd) and its text lines."""
        if self.service_shown:          # redrawn in place: a remove and play would show the slides below
            lines = {"line{}".format(i): text for i, text in enumerate(lines)}
            self._send("slides_play", {"service": {"action": "update", "key": "service", "expire": None}},
                       priority=SERVICE_PRIORITY, need_data=False, draw=draw or [], **lines)
            return
        self.text_show("service", lines, SERVICE_PRIORITY, draw=draw or [])
        self.service_shown = self.connected(need_data=False)

    def service_hide(self):
        self.service_shown = False
        self.shown.discard("service")               # the menu goes away: the attract effects take over
        self._send("slides_play", {"service": {"action": "remove", "key": "service", "expire": None}},
                   need_data=False)

    def confirm_show(self, draw):
        """The end-the-game question before the service menu opens in a game (tron/os_layer.py, not in the
        ROM), above every deff."""
        self.text_show("service_confirm", [], SERVICE_PRIORITY, draw=draw)

    def confirm_hide(self):
        self.shown.discard("service_confirm")
        self._send("slides_play", {"service_confirm": {"action": "remove", "key": "service_confirm",
                                                       "expire": None}}, need_data=False)

    # ------------------------------------------------------------------ sounds

    def sound_stop(self, call):
        """Stop every sample of sound call `call` (FUN_0002ceb4)."""
        pool = self.data["pools"].get(call) if self.data else None
        for sample in (pool or {}).get("samples", []):
            self._send("sounds_play", {sample: {"action": "stop", "key": sample}})

    def sound(self, call, index=None):
        if not self.data:
            return
        if 1 <= call <= 8:                             # channel stop
            if self.music_key:
                self._send("sounds_play", {self.music_key: {"action": "stop", "key": self.music_key}})
                self.music_key = None
            return
        pool = self.data["pools"].get(call)
        if not pool:
            return
        samples = pool["samples"]
        if index is not None and index < len(samples):  # the rules picked the sample (sound lengths)
            sample = samples[index]
        elif pool["type"].startswith("random"):
            sample = samples[self.os.random.randrange(len(samples))]
        else:                                          # sequence
            n = self.counters.get(call, 0)
            self.counters[call] = n + 1
            sample = samples[n % len(samples)]
        track = pool["track"]
        settings = {"action": "play", "bus": track, "key": sample}
        if track == "music":
            if self.music_key:
                self._send("sounds_play", {self.music_key: {"action": "stop", "key": self.music_key}})
            self.music_key = sample
            settings["loops"] = -1
        self._send("sounds_play", {sample: settings})
