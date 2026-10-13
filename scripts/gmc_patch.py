#!/usr/bin/env python3
"""Three changes to GMC 1.0.0 in game/addons/mpf-gmc (downloaded, not in git), applied idempotently.

1. GMC's poll thread parses whatever bytes the socket holds as whole lines. MPF's "settings" message at connect
is large (every adjustment with its value labels), so a read can end inside it: GMC then parses half a
message, `JSON.parse_string` returns null, `json.error` raises a script error and the BCP thread stops.
Nothing MPF sends after that is handled: no sounds, no music, no callouts (slides queued before may show).
The patch keeps the unfinished end of a read and prepends it to the next one.
2. GMC looks keys up in gmc.cfg [keyboard] by their layout label only, so on AZERTY the number row (which
needs Shift for digits) and "/" never match. A key not found by label is now also looked up by its physical
position on a US keyboard.
Upstream (mpf-gmc main, 2026-10) has the same code for 1 and 2.
3. GMC builds every slide from its scene at each show and frees it at its removal. The display effects' slides
(game/tron/dmd_slide.gd) are kept when removed; media.gd get_slide_instance() takes a kept one back first. setup.py, run.py and the Docker entrypoint call patch(); it does nothing once applied.

    python scripts/gmc_patch.py        # patch now; prints what it did
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import toolchain as tc  # noqa: E402

MARK = "# tron patch: partial BCP lines"
# every edit carries "# tron patch" (MARK's start), so a file holds the patch when TAG is in it
TAG = "# tron patch"

EDITS = [
    ("scripts/bcp_server.gd",
     "var _client: StreamPeerTCP\n",
     "var _client: StreamPeerTCP\n" + MARK + " (scripts/gmc_patch.py): the unfinished end of the last read\n"
     "var _rx_partial := \"\"\n"),
    ("scripts/bcp_server.gd",
     "\t\t_client = _server.take_connection()\n",
     "\t\t_client = _server.take_connection()\n\t\t_rx_partial = \"\"\n"),
    ("scripts/bcp_server.gd",
     "\t\tvar messages := _client.get_string(bytes).split(\"\\n\")\n",
     "\t\t" + MARK + ": parse complete lines only, keep the rest for the next read\n"
     "\t\tvar data := _rx_partial + _client.get_string(bytes)\n"
     "\t\tvar cut := data.rfind(\"\\n\")\n"
     "\t\t_rx_partial = data.substr(cut + 1)\n"
     "\t\tvar messages := PackedStringArray()\n"
     "\t\tif cut >= 0:\n"
     "\t\t\tmessages = data.substr(0, cut).split(\"\\n\")\n"),
    ("mpf_gmc.gd",                         # keys by position too, so the [keyboard] map works on AZERTY & co
     "\tif keycode in keyboard:\n",
     "\t" + MARK.replace("partial BCP lines", "keyboard layouts") + ": a key that is not in [keyboard] by its\n"
     "\t# label is looked up by its position on a US QWERTY keyboard (on AZERTY the '(' key is the 5 key)\n"
     "\tif not keycode in keyboard:\n"
     "\t\tvar physical = OS.get_keycode_string(event.get_physical_keycode_with_modifiers()).to_upper()\n"
     "\t\tif physical in keyboard:\n"
     "\t\t\tkeycode = physical\n"
     "\tif keycode in keyboard:\n"),
    ("scripts/media.gd",                   # display effects' slides reused (game/tron/dmd_slide.gd)
     "\tassert(slide_name in slides, \"Unknown slide name '%s'\" % slide_name)\n",
     "\tassert(slide_name in slides, \"Unknown slide name '%s'\" % slide_name)\n"
     "\t" + MARK.replace("partial BCP lines", "slide pool") + ": a slide kept from an earlier show\n"
     "\t# (res://tron/dmd_slide.gd) is shown again instead of building a new one from its scene\n"
     "\tif not preload_only:\n"
     "\t\tvar kept = load(\"res://tron/dmd_slide.gd\").take(slide_name)\n"
     "\t\tif kept:\n"
     "\t\t\treturn kept\n"),
    ("scripts/bcp_parse.gd",               # a bad message is logged instead of stopping the BCP thread
     "\t\t\tresult.error = \"Error %s parsing trigger: %s\" % [json.error, message]\n",
     "\t\t\tresult.error = \"Error parsing trigger: %s\" % message   " + MARK + "\n"),
]


def patch(gmc_dir=None, quiet=False):
    """Apply the edits; returns "patched", "in place", "missing" (no GMC yet) or raises on an unknown GMC."""
    gmc_dir = gmc_dir or tc.GMC_DIR
    if not os.path.exists(os.path.join(gmc_dir, "plugin.cfg")):
        return "missing"
    texts = {}
    for rel, _old, _new in EDITS:
        if rel not in texts:
            with open(os.path.join(gmc_dir, *rel.split("/")), encoding="utf-8", newline="") as f:
                texts[rel] = f.read()
    if all(TAG in t for t in texts.values()):
        return "in place"
    for rel, old, new in EDITS:
        text = texts[rel]
        if new in text:
            continue
        crlf = "\r\n" in text
        o, n = (old.replace("\n", "\r\n"), new.replace("\n", "\r\n")) if crlf else (old, new)
        if text.count(o) != 1:
            raise SystemExit("GMC {}: unexpected {} (not GMC {}?); remove game/addons/mpf-gmc and re-run setup.py"
                             .format(gmc_dir, rel, tc.GMC_VERSION))
        texts[rel] = text.replace(o, n)
    for rel, text in texts.items():
        with open(os.path.join(gmc_dir, *rel.split("/")), "w", encoding="utf-8", newline="") as f:
            f.write(text)
    if not quiet:
        print("   GMC BCP reader patched (scripts/gmc_patch.py)", flush=True)
    return "patched"


if __name__ == "__main__":
    print(patch(quiet=True))
