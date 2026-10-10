"""game/pup.cfg (+ game/pup.local.cfg): the PuP settings Godot and MPF share.

The files are Godot ConfigFile INI with JSON values, so both sides parse them the same way.
TRON_PUP=0 in the environment disables the PuP whatever the files say.
"""
import json
import os

GAME = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ROOT = os.path.dirname(GAME)
FILES = ("pup.cfg", "pup.local.cfg")


def _parse(path, into):
    section = None
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line[0] in ";#":
                continue
            if line.startswith("[") and line.endswith("]"):
                section = into.setdefault(line[1:-1].strip(), {})
                continue
            if "=" not in line or section is None:
                continue
            key, value = line.split("=", 1)
            try:
                section[key.strip()] = json.loads(value.strip())
            except ValueError:
                section[key.strip()] = value.strip().strip('"')


def load(game_dir=GAME):
    cfg = {}
    for name in FILES:
        path = os.path.join(game_dir, name)
        if os.path.exists(path):
            _parse(path, cfg)
    pup = cfg.setdefault("pup", {})
    if os.environ.get("TRON_PUP", "").strip().lower() in ("0", "false", "no", "off"):
        pup["enabled"] = False
    return cfg


def pack_dir(cfg, root=ROOT):
    return os.path.join(root, cfg.get("pup", {}).get("pack_dir", "pup_pack/trn_174h"))


def media_dir(cfg, root=ROOT):
    return os.path.join(root, cfg.get("pup", {}).get("media_dir", "pup_media/trn_174h"))
