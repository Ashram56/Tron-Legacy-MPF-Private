"""MPF side of the PuP Pack: game events -> PuP triggers -> the Godot PuP player, and the ROM music mute.

The "pup" mode (game/modes/pup/) is never started: its code only hooks the machine at init, so the rules
in game/tron/ are untouched. Commands go to Godot as BCP "pup_play" triggers. Godot answers "pup_ready" when
its PuP player has its windows and media (game/pup/pup_player.gd); only then:
- the start-up triggers fire (D0=1),
- with [pup] ost_music the ROM's music calls (the "music" track sound pools) are dropped and the running ROM
  music is stopped, so the PuP OST (PuP screen 15) is the only music. Without a ready PuP player (no media,
  PuP disabled, unit tests) the ROM music plays as before.
"""
import logging

from mpf.core.mode import Mode

from tron_pup import engine, settings

log = logging.getLogger("tron.pup")
BCP_CLIENT = "local_display"
HELLO_TRIES, HELLO_SECONDS = 15, 2.0


class PupMode(Mode):

    def mode_init(self):
        self.cfg = settings.load()
        self.pup = self.cfg.get("pup", {})
        self.engine = None
        self.ready = False
        self.mute = False
        self._attract = None
        self._sound = None
        if not self.pup.get("enabled", True):
            log.info("PuP disabled (game/pup.cfg or TRON_PUP=0)")
            return
        pack = settings.pack_dir(self.cfg)
        try:
            self.engine = engine.build(pack, self.send, self.machine.clock.get_time)
        except FileNotFoundError:
            log.warning("PuP Pack not found at %s (git submodule update --init pup_pack): no PuP", pack)
            return
        events = self.machine.events
        for name in self.engine.event_names:
            events.add_handler(name, self._event, _pup_event=name)
        for switch in self.engine.switches:
            if switch in self.machine.switches:
                self.machine.switch_controller.add_switch_handler(switch, self._switch, state=1,
                                                                  callback_kwargs={"switch": switch})
        events.add_handler("pup_ready", self._ready)
        events.add_handler("init_phase_5", self._hello)
        events.add_handler("mode_attract_started", self._attract_start)
        events.add_handler("mode_attract_stopped", self._attract_stop)
        log.info("PuP: %d events, %d switches; rows without a mapping: %s", len(self.engine.events),
                 len(self.engine.switches), ", ".join(str(r.id) for r in self.engine.unmapped) or "none")

    # ------------------------------------------------------------------ triggers

    def _event(self, _pup_event, **kwargs):
        self.engine.on_event(_pup_event, **kwargs)

    def _switch(self, switch):
        self.engine.on_switch(switch)

    def send(self, cmd):
        if self.ready:
            self._bcp("pup_play", **{k: v for k, v in cmd.items() if v is not None})

    def _bcp(self, name, **kwargs):
        """BCP trigger straight to GMC (as tron/media_bridge.py does: GMC registers no MPF handler for it)."""
        bcp = getattr(self.machine, "bcp", None)
        transport = getattr(bcp, "transport", None) if bcp else None
        client = transport.get_named_client(BCP_CLIENT) if transport else None
        if not client:
            return False
        bcp.interface.bcp_trigger_client(client=client, name=name, **kwargs)
        return True

    def _hello(self, tries=HELLO_TRIES, **kwargs):
        """Ask Godot's PuP player whether it is up; it answers pup_ready. Asked again until it answers."""
        if self.ready or tries <= 0:
            return
        self._bcp("pup_hello")
        self.machine.clock.schedule_once(lambda: self._hello(tries - 1), HELLO_SECONDS)

    def _ready(self, **kwargs):
        """Godot's PuP player is up (sent again when Godot restarts)."""
        first = not self.ready
        self.ready = True
        self.set_music_mute(bool(self.pup.get("ost_music", True)) and kwargs.get("ost", True) not in (False, 0, "0"))
        self.machine.events.post("pup_boot")
        if first:
            self.machine.events.post("pup_power_up")

    def _attract_start(self, **kwargs):
        self._attract_stop()
        seconds = float(self.pup.get("attract_cycle_seconds", 60.0))
        if seconds > 0:
            self._attract = self.machine.clock.schedule_interval(
                lambda: self.machine.events.post("pup_attract_cycle"), seconds)

    def _attract_stop(self, **kwargs):
        if self._attract:
            self.machine.clock.unschedule(self._attract)
            self._attract = None

    # ------------------------------------------------------------------ ROM music

    def set_music_mute(self, mute):
        """Drop the ROM's music calls (sound pools on the "music" track) while the PuP OST plays."""
        tron = getattr(self.machine, "tron", None)
        bridge = getattr(tron, "media", None)
        if bridge is None:
            return
        self.mute = mute
        if self._sound is None:
            self._sound = bridge.sound

            def sound(call, index=None):
                if self.mute and self.is_music(bridge, call):
                    return None
                return self._sound(call, index)
            bridge.sound = sound
        if mute and bridge.music_key:                  # ROM music already playing: stop it
            self._sound(1)

    @staticmethod
    def is_music(bridge, call):
        pool = bridge.data["pools"].get(call) if bridge.data else None
        return bool(pool) and pool.get("track") == "music"
