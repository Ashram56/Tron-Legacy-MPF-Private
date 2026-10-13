"""PuP trigger engine: which triggers.pup rows a game event fires, and their RestSeconds.

No MPF here (game/tron_pup/mode.py wires it to the machine), so the unit tests drive it directly.
A fired row becomes a command for the Godot PuP player (game/pup/pup_player.gd), which owns the screens,
playlists, priorities and the Loop column (Loop, SetBG, StopFile, StopPlayer, SkipSamePrty).
"""
import os
import re

from tron_pup import pupfiles

MAP_FILE = os.path.join(os.path.dirname(__file__), "trigger_map.yaml")
EVENT = re.compile(r"^\s*([\w.]+)\s*(?:\{\s*(\w+)\s*==\s*([\w.\-]+)\s*\})?\s*$")


def load_map(path=MAP_FILE):
    from ruamel.yaml import YAML
    with open(path, encoding="utf-8") as f:
        data = YAML(typ="safe").load(f) or {}
    return {key: {int(k): v for k, v in (data.get(key) or {}).items()} for key in ("dmd", "switches", "override")}


def parse_event(text):
    """'tron_deff_112{award==1}' -> ('tron_deff_112', ('award', '1')); 'tron_deff_25' -> ('tron_deff_25', None)."""
    m = EVENT.match(str(text))
    if not m:
        raise ValueError("bad PuP event {!r}".format(text))
    return m.group(1), (m.group(2), m.group(3)) if m.group(2) else None


class Engine:

    def __init__(self, triggers, trigger_map, send, now):
        """triggers: pupfiles.Trigger rows; send(command dict); now() -> seconds."""
        self.send, self.now = send, now
        self.events = {}            # event name -> [(condition, Trigger)]
        self.switches = {}          # switch name -> [Trigger]
        self.unmapped = []          # rows this game cannot fire (unknown code or no mapping)
        self.last = {}              # trigger id -> time it last fired (RestSeconds)
        for row in triggers:
            if not row.active or not row.terms or row.screen is None:
                continue
            self._bind(row, trigger_map)

    def _bind(self, row, trigger_map):
        events = trigger_map["override"].get(row.id)
        if events is None and len(row.terms) == 1:
            kind, num, _ = row.terms[0]
            if kind == "D":
                events = trigger_map["dmd"].get(num)
            elif kind == "W" and num in trigger_map["switches"]:
                self.switches.setdefault(trigger_map["switches"][num], []).append(row)
                return
        if not events:
            self.unmapped.append(row)
            return
        for text in events:
            name, cond = parse_event(text)
            self.events.setdefault(name, []).append((cond, row))

    # ------------------------------------------------------------------ firing

    def on_event(self, name, **kwargs):
        rows = [row for cond, row in self.events.get(name, ())
                if cond is None or str(kwargs.get(cond[0])) == cond[1]]
        self.fire(rows)

    def on_switch(self, name):
        self.fire(self.switches.get(name, ()))

    def fire(self, rows):
        """Rows in triggers.pup order; a row resting since its last fire is skipped. Two rows that would send
        the same command (several captures of one display effect) send it once."""
        now = self.now()
        sent = set()
        for row in sorted(rows, key=lambda r: r.id):
            last = self.last.get(row.id)
            if last is not None and row.rest and now - last < row.rest:
                continue
            self.last[row.id] = now
            cmd = row.command()
            key = (cmd["screen"], cmd["playlist"], cmd["file"], cmd["mode"], cmd["priority"])
            if key in sent:
                continue
            sent.add(key)
            self.send(cmd)

    @property
    def event_names(self):
        return sorted(self.events)


def build(pack_dir, send, now, map_path=MAP_FILE):
    return Engine(pupfiles.load_triggers(pack_dir), load_map(map_path), send, now)
