"""Device numbers: the SAM number a device has on this machine, and its number in the ROM's own numbering.

The rules (lamps.py, the traces) count lamps and coils as the LE 1.74 ROM does, but an overlay can renumber a
device: the P-ROC writes SAM lamp 17 as "L17" (rom/proc_numbers*.yaml) and the Pro moves it to another lamp
(machine_pro.yaml). So the rules look a device's ROM number up by name in the asset package's tables
(game/config/rom/*.yaml), and the service menu shows the number the device has on this machine.
"""
import os
import re

_ROM = {}


def sam_number(device):
    """The device's SAM number on this machine: "1", "D9", "3", "17" (P-ROC's "S01", "SD9", "C03", "L17" read back)."""
    text = str(device.config.get("number", ""))
    m = re.fullmatch(r"(SD|S|C|L)(\d+)", text)
    if m:
        return ("D" if m.group(1) == "SD" else "") + str(int(m.group(2)))
    return text


def rom_numbers(machine, section):
    """{device name: number} of the switches, coils or lights in the ROM's own (LE) numbering, for devices with a
    plain SAM number (not the aux bus tubes, not the Pro's own flashers)."""
    path = os.path.join(machine.machine_path, "config", "rom", section + ".yaml")
    if path not in _ROM:
        from ruamel.yaml import YAML
        with open(path, encoding="utf-8") as f:
            data = (YAML(typ="safe").load(f) or {}).get(section) or {}
        _ROM[path] = {name: int(cfg["number"]) for name, cfg in data.items()
                      if cfg and str(cfg.get("number", "")).isdigit()}
    return _ROM[path]


# The Pro 1.74 fires its lower flashers 22 / 23 with the ramp flashers 19 / 25 in every effect where the LE fires
# only the ramp flashers (assets/rom_data/pro/README.md, "Back/lower flashers": same timing; the pairing of
# left/right is inferred).
PRO_COMPANIONS = {"f_left_ramp": "f_lower_left", "f_right_ramp": "f_lower_right"}


def pro_companion_flashers(machine):
    """On a Pro (machine var machine_variant), make each pulse of a ramp flasher, from the rules or a show, also
    pulse its lower flasher. Does nothing on an LE or a machine without the Pro's flashers."""
    if machine.variables.get_machine_var("machine_variant") != "pro":
        return
    coils = getattr(machine, "coils", {})
    for name, companion in PRO_COMPANIONS.items():
        if name not in coils or companion not in coils or getattr(coils[name], "_pro_companion", None):
            continue
        coil, other = coils[name], coils[companion]
        pulse = coil.pulse

        def both(*args, _pulse=pulse, _other=other, **kwargs):
            _other.pulse(*args, **kwargs)
            return _pulse(*args, **kwargs)
        coil.pulse = both
        coil._pro_companion = companion
