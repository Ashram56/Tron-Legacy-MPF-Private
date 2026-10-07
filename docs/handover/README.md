# Handover: rebuilding a Stern SAM game in MPF

Start here. These files are written for an AI agent taking over, so each one is short, dense and
self-contained: read only the one your task needs.

| File | Read it when | Size |
|---|---|---|
| [sam_to_mpf_playbook.md](sam_to_mpf_playbook.md) | You build or maintain an MPF recreation of **any** Stern SAM game from ROM-derived specs. Architecture, build order, verification loop and every gotcha that cost real time. Game agnostic; Tron is only the worked example. | ~15 min |
| [dmd_hd_upscaling.md](dmd_hd_upscaling.md) | You work on the optional HD display (128x32 DMD drawn at any window size). Separate from the rules work on purpose. | ~5 min |
| [rom_decomp_feedback.md](rom_decomp_feedback.md) | Hand this to the agent that decompiles the ROM and produces the asset/spec repo. What the MPF build consumed, what was missing or wrong, and what to deliver for the next game. | ~8 min |

Not covered here: DMD colorization (its own branch and docs).

## Token rules for the agent taking over

1. Read this README, then one doc above. Do not read the whole repo: every doc names the exact file to open.
2. Grep the specs, never read them whole. Spec files are long; the rules you need are a section.
3. Trust the code's module docstrings: each `game/tron/*.py` and `scripts/*.py` opens with what it models
   and which ROM addresses it follows. `sed -n '1,/^"""$/p' FILE` reads only that.
4. Commit messages carry the "why" of each fix: `git log --no-merges --format='%h %s%n%b'` (about 33 KB
   for the whole Tron build) is cheaper than rediscovering a bug.
5. Run the checks instead of reasoning about them: `pytest -q tests` and `scripts/trace_check.py <scenario>`
   answer "does it match the ROM" faster than reading the trace.

## Where the Tron instance lives

| What | Where |
|---|---|
| Game repo (MPF + Godot) | `Ashram56/Tron-Legacy-MPF`, stacked phase branches `phase2-machine` .. `phase11-hd` (PRs #2-#9), VPX bridge PR #10 |
| Asset/spec repo (ROM-derived) | `Ashram56/Tron-Legacy-LE-ROM-Decryption`, git submodule at `assets/` |
| ROM | Tron Legacy LE v1.74, PinMAME set `trn_174h`; the ROM binary is in neither repo. The game runs the LE rules on Pro (default) or LE hardware: `docs/hardware.md`, "Pro or LE" |
| Coil times | the ROM's, generated into `game/config/rom/coil_times.yaml` from `assets/rom_data/io/coils.csv` |
| User docs | `README.md`, `docs/requirements.md`, `docs/hardware.md` (P-ROC), `docs/vpx.md` (Visual Pinball X) |
| Departures from the ROM | `docs/rom_differences.md`: read before changing a rule; add every new departure there |
