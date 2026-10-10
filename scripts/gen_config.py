#!/usr/bin/env python3
"""Generate game/config/rom/*.yaml from the asset package (adds MPF's config_version header).

The asset package's YAML has no "#config_version=6" first line, which MPF requires. These files are
generated, not edited: re-run after every asset sync (scripts/setup.py and the tests do it).

It also writes rom/proc_numbers.yaml, the P-ROC addresses of every switch, coil and light (hw_proc.yaml),
from the SAM numbers in rom/*.yaml and hardware.yaml, in the strings libpinproc's decode() takes for
driverboards sternSAM (PRDecode in libpinproc src/pinproc.cpp):
- matrix switch n (1-64) -> "Snn", dedicated switch "D<n>" (1-24) -> "SD<n>"
- coil/flasher n (1-32) -> "Cnn"; 33-40 are latched from the IO board's aux bus, which the P-ROC does
  not drive as drivers, so they stay on the virtual platform
- lamp n (1-80) -> "Lnn"; the ramp light tubes ("aux_strobe_...") are aux bus outputs too: virtual
  platform, driven by tron/proc_hardware.py when enabled

Two machines (docs/hardware.md, "Pro or LE"): the asset package numbers everything as the LE 1.74 ROM does.
rom/pro_numbers.yaml moves each device to its Pro 1.74 number (assets/io/pro_vs_le_io_map.csv), puts the LE
devices the Pro does not have on the virtual platform and adds the Pro's own flashers; rom/proc_numbers_pro.yaml
is the same for the P-ROC. rom/coil_times.yaml holds the ROM's coil drive times (assets/rom_data/io/coils.csv).
"""
import csv
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "assets", "mpf_package", "config")
DST = os.path.join(ROOT, "game", "config", "rom")
FILES = ["switches.yaml", "coils.yaml", "lights.yaml", "settings.yaml"]
CONFIG = os.path.join(ROOT, "game", "config")
PROC_SOURCES = ["rom/switches.yaml", "rom/coils.yaml", "rom/lights.yaml", "hardware.yaml"]
PRO_MAP = os.path.join(ROOT, "assets", "io", "pro_vs_le_io_map.csv")
COIL_TIMES = os.path.join(ROOT, "assets", "rom_data", "io", "coils.csv")
SECTION = {"switch": "switches", "coil": "coils", "lamp": "lights"}
# Outputs the Pro renames but uses for the same flasher, so the rules keep driving them on the Pro (the map calls
# them absent on the other model because the names differ):
# - the disc: LE 31 RED DISC / 32 BLUE DISC, Pro 31 RED DISC (LEFT) / 32 RED DISC (RIGHT);
# - the ramps: LE 19 LEFT RAMP / 25 RIGHT RAMP, Pro 19 BACK CENTER / 25 BACK LEFT: the Pro decompile shows Pro 19 / 25
#   take the LE ramp flashers' slots in every effect (assets/rom_data/pro/README.md).
SAME_OUTPUT = {("coil", 31), ("coil", 32), ("coil", 19), ("coil", 25)}
PRO_FLASHER_PULSE_MS = 48     # the Pro's lower flashers 22 / 23: the ramp flashers' 48 ms (assets/rom_data/pro/README.md)


def _write(path, out):
    if not os.path.exists(path) or open(path, encoding="utf-8").read() != out:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(out)


def proc_number(section, number):
    """SAM number -> (libpinproc number string, None) or (None, reason it stays virtual)."""
    text = str(number).strip()
    if section == "switches":
        m = re.fullmatch(r"D(\d+)", text)
        if m and 1 <= int(m.group(1)) <= 24:
            return "SD{}".format(int(m.group(1))), None
        if text.isdigit() and 1 <= int(text) <= 64:
            return "S{:02d}".format(int(text)), None
    elif section == "coils":
        if text.isdigit() and 1 <= int(text) <= 32:
            return "C{:02d}".format(int(text)), None
        if text.isdigit() and 33 <= int(text) <= 40:
            return None, "aux bus latch output, not a P-ROC driver"
    elif section == "lights":
        if text.isdigit() and 1 <= int(text) <= 80:
            return "L{:02d}".format(int(text)), None
        if text.startswith("aux_strobe_"):
            return None, "aux bus RGB tube, driven by tron/proc_hardware.py"
    raise ValueError("{} number {!r} is not a SAM number".format(section, number))


def _yaml():
    from ruamel.yaml import YAML        # MPF's YAML library (the .venv has no PyYAML)
    return YAML(typ="safe")


def le_numbers():
    """{section: [(name, SAM number)]} of rom/*.yaml and hardware.yaml: the LE machine."""
    yaml = _yaml()
    out = {}
    for section in ("switches", "coils", "lights"):
        entries = out.setdefault(section, [])
        for source in PROC_SOURCES:
            with open(os.path.join(CONFIG, source), encoding="utf-8") as f:
                data = yaml.load(f) or {}
            for name, cfg in (data.get(section) or {}).items():
                if cfg and "number" in cfg:
                    entries.append((name, cfg["number"]))
    return out


def slug(name):
    return re.sub(r"[^a-z0-9]+", "_", name.lower().replace("flash:", "")).strip("_")


def pro_changes():
    """From assets/io/pro_vs_le_io_map.csv:
    moves {(section, LE number): Pro number or None (no such device on the Pro)},
    added [(section, name, Pro number, Pro ROM name)]: Pro devices the LE does not have."""
    moves, added = {}, []
    with open(PRO_MAP, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            kind, number = row["kind"], int(row["number"])
            if kind not in SECTION:
                continue
            section = SECTION[kind]
            if (kind, number) in SAME_OUTPUT:
                continue
            on_pro = row["le_name_on_pro_at"].strip()
            if row["le_1.74_name"] not in ("", "NOT USED") and on_pro != str(number):
                moves[(section, number)] = int(on_pro) if on_pro.isdigit() else None
            pro_name = row["pro_1.74_name"]
            if row["pro_name_on_le_at"].strip() == "absent" and pro_name not in ("", "NOT USED"):
                added.append((section, ("f_" if pro_name.startswith("FLASH:") else "c_") + slug(pro_name), number,
                              pro_name))
    return moves, added


def pro_machine(le):
    """[(section, name, Pro number or None, note)] for every device whose number differs on the Pro."""
    moves, added = pro_changes()
    out = []
    for section, entries in le.items():
        for name, number in entries:
            key = (section, int(number)) if str(number).isdigit() else None
            if key in moves:
                pro = moves[key]
                out.append((section, name, pro, "LE {}".format(number) if pro else "LE {}, not on the Pro".format(
                    number)))
    out += [(section, name, number, "Pro only: {}".format(pro_name)) for section, name, number, pro_name in added]
    return out


def gen_pro_numbers(le):
    lines = ["#config_version=6",
             "# GENERATED by scripts/gen_config.py from assets/io/pro_vs_le_io_map.csv: the Tron Legacy Pro 1.74",
             "# numbers of every device whose number differs from the LE's. LE devices the Pro does not have go to the",
             "# virtual platform; the Pro's own flashers are added (tron/hw_numbers.py fires them with the ramp flashers).",
             "# Included by machine_pro.yaml."]
    changes = pro_machine(le)
    for section in ("switches", "coils", "lights"):
        lines.append("{}:".format(section))
        for sec, name, number, note in changes:
            if sec != section:
                continue
            lines.append("  {}:".format(name))
            if number is None:
                lines.append("    platform: virtual   # {}".format(note))
                continue
            lines.append("    number: {}   # {}".format(number, note))
            if note.startswith("Pro only"):
                lines.append("    label: \"{}\"".format(note.split(": ", 1)[1]))
                if name.startswith("f_"):
                    lines.append("    default_pulse_ms: {}   # the Pro ROM's pulse in the ramp flasher effects".format(
                        PRO_FLASHER_PULSE_MS))
    _write(os.path.join(DST, "pro_numbers.yaml"), "\n".join(lines) + "\n")


def gen_proc_numbers(le, pro=False):
    entries = {section: list(items) for section, items in le.items()}
    virtual = set()
    if pro:
        for section, name, number, _ in pro_machine(le):
            items = entries[section]
            if number is None:
                virtual.add((section, name))
            elif any(n == name for n, _ in items):
                entries[section] = [(n, number if n == name else v) for n, v in items]
            else:
                items.append((name, number))
    lines = ["#config_version=6",
             "# GENERATED by scripts/gen_config.py from {}{}:".format(
                 ", ".join(PROC_SOURCES), " and assets/io/pro_vs_le_io_map.csv" if pro else ""),
             "# P-ROC (driverboards sternSAM) numbers for every switch, coil and light of the {}. Included by {}.".format(
                 "Tron Legacy Pro" if pro else "Tron Legacy LE", "hw_proc.yaml" if pro else "hw_proc_le.yaml")]
    for section in ("switches", "coils", "lights"):
        lines.append("{}:".format(section))
        for name, number in entries[section]:
            lines.append("  {}:".format(name))
            if (section, name) in virtual:
                lines.append("    platform: virtual   # SAM {} on the LE: not on the Pro".format(number))
                continue
            proc, reason = proc_number(section, number)
            if proc:
                lines.append("    number: {}   # SAM {}".format(proc, number))
            else:
                lines.append("    platform: virtual   # SAM {}: {}".format(number, reason))
    _write(os.path.join(DST, "proc_numbers_pro.yaml" if pro else "proc_numbers.yaml"), "\n".join(lines) + "\n")


def gen_coil_times(le):
    """rom/coil_times.yaml: the drive times the ROM gives each coil (assets/rom_data/io/coils.csv, mpf_* columns)."""
    names = {int(number): name for name, number in le["coils"] if str(number).isdigit()}
    lines = ["#config_version=6",
             "# GENERATED by scripts/gen_config.py from assets/rom_data/io/coils.csv: the ROM's drive time for each coil",
             "# (coil descriptors, hardware rules and game calls, checked in the emulator). Included by config.yaml.",
             "coils:"]
    with open(COIL_TIMES, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            number = int(row["coil"])
            if number not in names or not row["kind"] or row["kind"] == "undefined":
                continue
            values = [("default_pulse_ms", row["mpf_default_pulse_ms"], int),
                      ("default_hold_power", row["mpf_default_hold_power"], float),
                      ("default_pulse_power", row["mpf_pulse_power"], float)]
            values = [(key, cast(text)) for key, text, cast in values if text.strip()]
            if not values:
                continue
            lines.append("  {}:   # {} {}: {}".format(names[number], number, row["name"], row["mpf_note"]))
            lines += ["    {}: {}".format(key, value) for key, value in values]
    _write(os.path.join(DST, "coil_times.yaml"), "\n".join(lines) + "\n")


def main():
    os.makedirs(DST, exist_ok=True)
    for name in FILES:
        with open(os.path.join(SRC, name), encoding="utf-8") as f:
            body = f.read()
        # MPF 0.80 has no "flashers:" section; flashers are plain coils there.
        body = body.replace("\nflashers:\n", "\n# (flashers, as coils for MPF 0.80)\n")
        # the package writes the setting group as "setting_type"; MPF 0.80's settings spec calls it "settingType"
        body = body.replace("    setting_type: ", "    settingType: ")
        out = "#config_version=6\n# GENERATED from assets/mpf_package/config/{} by scripts/gen_config.py\n{}".format(
            name, body)
        _write(os.path.join(DST, name), out)
    le = le_numbers()
    gen_proc_numbers(le)
    gen_proc_numbers(le, pro=True)
    gen_pro_numbers(le)
    gen_coil_times(le)
    return 0


if __name__ == "__main__":
    sys.exit(main())
