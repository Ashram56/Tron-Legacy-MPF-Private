#!/usr/bin/env python3
"""Write the MPF version of a Visual Pinball X table's script, next to the table, as VPX's script override.

    python scripts/vpx_table.py "C:\\Visual Pinball\\Tables\\Tron Legacy (Stern 2011) VPW Mod v1.1.vpx"

reads the script out of the .vpx (it is never modified), swaps PinMAME for MPF and writes
"Tron Legacy (Stern 2011) VPW Mod v1.1.vbs" beside it. VPX loads a .vbs with the table's name instead of the
script inside the table (VPX 10.7 and later), so deleting or renaming that file is all it takes to play the table
with PinMAME again. Needs olefile (`python scripts/setup.py --vpx`). docs/vpx.md has the whole set-up.

The change, in the script: `LoadVPM "...", "sam.VBS", ...` (which creates VPinMAME.Controller) becomes
`LoadMPF "sam.VBS"`: the same VPinMAME helper scripts (core.vbs, sam.vbs: keys, timers, ball stacks, fast flips)
with the TronMPF.Controller COM object (scripts/vpx_bridge.py) as the controller. One line goes into the table's
KeyDown sub: End opens and closes the coin door (switch -4, game/config/hw_vpx.yaml), which VPinMAME does by
itself and sam.vbs has no switch for. Everything else in the table script stays as it is, since MPF answers the
controller calls the way PinMAME does (game/tron/vpx_hardware.py).
"""
import argparse
import os
import re
import struct
import sys

MARKER = "' Tron MPF bridge:"
KEYDOWN = re.compile(r'^([ \t]*)Sub[ \t]+\w+_KeyDown[ \t]*\([ \t]*(?:ByVal[ \t]+)?(\w+)[ \t]*\)[^\r\n]*(?=\r?$)',
                     re.I | re.M)
KEY_END = 207           # DirectInput DIK_END: PinMAME's coin door key
SW_COIN_DOOR = -4       # game/config/hw_vpx.yaml s_coin_door_open
COIN_DOOR_LINE = ("{indent}\tIf {var} = {key} Then Controller.Switch({sw}) = Not Controller.Switch({sw}) : Exit Sub"
                  "\t{marker} End opens and closes the coin door, as in PinMAME")
LOADVPM = re.compile(r'^([ \t]*)LoadVPM[ \t]+"[^"\r\n]*"[ \t]*,[ \t]*"(sam\.vbs)"[^\r\n]*(?=\r?$)', re.I | re.M)

LOADER = '''{indent}{marker} the game runs in MPF (github.com/Ashram56/Tron-Legacy-MPF), not PinMAME. Written by
{indent}' scripts/vpx_table.py; delete this .vbs to play the table with PinMAME again. Was: {original}
{indent}LoadMPF "{vbs}"

Sub LoadMPF(VBSfile)
	On Error Resume Next
	ExecuteGlobal GetTextFile(VBSfile)
	If Err Then MsgBox "Unable to open " & VBSfile & ". Ensure that it is in the Scripts folder of Visual Pinball." & vbNewLine & Err.Description
	Err.Clear
	InitializeOptions	' controller.vbs of VPX 10.7+ (older ones have none)
	Err.Clear
	B2SOn = False
	Set Controller = CreateObject("TronMPF.Controller")
	If Err Then MsgBox "Can't load the Tron MPF bridge (TronMPF.Controller). Register it once, as Administrator:" & vbNewLine & _
		".venv\\Scripts\\python scripts\\vpx_bridge.py --register" & vbNewLine & Err.Description
	On Error Goto 0
End Sub
'''


def read_vpx_script(path):
    """The table script stored in a .vpx: the CODE record of the GameStg/GameData stream (VPX's BIFF format:
    int32 length, 4-byte tag, data; CODE is followed by an int32 string length and the script itself)."""
    try:
        import olefile
    except ImportError:
        raise SystemExit("olefile is needed to read a .vpx: python scripts/setup.py --vpx "
                         "(or .venv/bin/python -m pip install olefile)")
    with olefile.OleFileIO(path) as ole:
        data = ole.openstream("GameStg/GameData").read()
    i = 0
    while i + 8 <= len(data):
        length, tag = struct.unpack_from("<i4s", data, i)
        if tag == b"CODE":
            size, = struct.unpack_from("<i", data, i + 8)
            return data[i + 12:i + 12 + size]
        if tag == b"ENDB":
            break
        i += 4 + length
    raise SystemExit("{}: no script found in the table".format(path))


def patch_script(text):
    """The table script with MPF in place of PinMAME. text is str (the script as VPX stores it, cp1252)."""
    if MARKER in text:
        raise ValueError("this script already uses the MPF bridge")
    matches = list(LOADVPM.finditer(text))
    if len(matches) != 1:
        raise ValueError('expected one `LoadVPM "...", "sam.VBS", ...` line, found {}'.format(len(matches)))
    m = matches[0]
    newline = "\r\n" if "\r\n" in text else "\n"
    loader = LOADER.format(indent=m.group(1), marker=MARKER, original=m.group(0).strip(), vbs=m.group(2))
    text = text[:m.start()] + loader.replace("\n", newline).rstrip(newline) + text[m.end():]
    keydown = list(KEYDOWN.finditer(text))
    if len(keydown) != 1:
        return text                     # no table KeyDown sub to hook: the coin door stays closed
    k = keydown[0]
    line = COIN_DOOR_LINE.format(indent=k.group(1), var=k.group(2), key=KEY_END, sw=SW_COIN_DOOR, marker=MARKER)
    return text[:k.end()] + newline + line + text[k.end():]


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("table", help="the .vpx (or a .vbs exported from it)")
    p.add_argument("-o", "--output", help="where to write the script (default: the table's name with .vbs)")
    p.add_argument("--force", action="store_true", help="overwrite an existing .vbs that this tool did not write")
    args = p.parse_args(argv)
    if args.table.lower().endswith(".vpx"):
        raw = read_vpx_script(args.table)
    else:
        with open(args.table, "rb") as f:
            raw = f.read()
    text = raw.decode("cp1252", errors="surrogateescape")
    try:
        patched = patch_script(text)
    except ValueError as e:
        raise SystemExit("{}: {}".format(args.table, e))
    out = args.output or os.path.splitext(args.table)[0] + ".vbs"
    if os.path.abspath(out) == os.path.abspath(args.table):
        raise SystemExit("the output would replace the input; give -o")
    if os.path.exists(out) and not args.force:
        with open(out, "rb") as f:
            if MARKER.encode() not in f.read():
                raise SystemExit("{} exists and was not written by this tool (keep it, or use --force)".format(out))
    with open(out, "wb") as f:
        f.write(patched.encode("cp1252", errors="surrogateescape"))
    print("wrote {} ({} lines): VPX now runs this table with MPF; delete it to go back to PinMAME".format(
        out, patched.count("\n") + 1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
