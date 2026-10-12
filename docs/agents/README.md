# Tron Legacy: game page for the agents

The agents that built this game, and the knowledge base they share, live in the game-agnostic repository
**[Ashram56/Stern-SAM-Decryption](https://github.com/Ashram56/Stern-SAM-Decryption)**. Start there:
[master plan](https://github.com/Ashram56/Stern-SAM-Decryption/blob/main/agents/README.md) (what the owner provides, which agent does what, in what order), then the one
agent file your task needs. This page holds only what is true of Tron: its inputs, where its pieces live, each
agent's Tron status and open work, and the owner's Tron decisions.

**Reading the agents.** In a session with Stern-SAM-Decryption attached or cloned beside this repository
(`../Stern-SAM-Decryption`), read the files there; otherwise read them on GitHub. Update them there (a PR on
Stern-SAM-Decryption) when you learn something any SAM game would need; update this page for Tron facts.

| Agent | Instructions (Stern-SAM-Decryption) | Tron section below |
|---|---|---|
| A, ROM extraction | [agents/rom_extraction.md](https://github.com/Ashram56/Stern-SAM-Decryption/blob/main/agents/rom_extraction.md) | [A](#a-rom-extraction) |
| B, VPX extraction | [agents/vpx_extraction.md](https://github.com/Ashram56/Stern-SAM-Decryption/blob/main/agents/vpx_extraction.md) | [B](#b-vpx-extraction) |
| C, strict recreation | [agents/recreation.md](https://github.com/Ashram56/Stern-SAM-Decryption/blob/main/agents/recreation.md) | [C](#c-strict-recreation) |
| D, VPX bridge | [agents/vpx_bridge.md](https://github.com/Ashram56/Stern-SAM-Decryption/blob/main/agents/vpx_bridge.md) | [D](#d-vpx-bridge) |
| E, improvements | [agents/improvement.md](https://github.com/Ashram56/Stern-SAM-Decryption/blob/main/agents/improvement.md) | [E](#e-improvements) |
| F, packaging | [agents/packaging.md](https://github.com/Ashram56/Stern-SAM-Decryption/blob/main/agents/packaging.md) | [F](#f-packaging) |
| G, PuP Pack | [agents/pup_pack.md](https://github.com/Ashram56/Stern-SAM-Decryption/blob/main/agents/pup_pack.md) | [G](#g-pup-pack) |
| Knowledge base | [knowledge/](https://github.com/Ashram56/Stern-SAM-Decryption/blob/main/knowledge/README.md): SAM to MPF playbook, HD DMD method, decomp feedback | |

## Tron's inputs (the kickoff values)

| Input | Tron |
|---|---|
| Game | Stern Tron Legacy LE, code v1.74; Pro v1.74 ported as a second model |
| ROM | PinMAME sets `trn_174h` (LE 1.74), `trn_17402` (Pro 1.74); never committed |
| VPX table | VPW Mod v1.1, in the project's files as `Tron Legacy (Stern 2011) VPW Mod v1.1.vpx` |
| Repositories | asset repo [Tron-Legacy-LE-ROM-Decryption](https://github.com/Ashram56/Tron-Legacy-LE-ROM-Decryption) (git submodule at `assets/`); game repo this one; colour work in the private repo `Ashram56/Tron-Legacy-MPF-Private` |
| Hardware | P-ROC on the SAM boards, Pro by default, LE selectable; VPX on Windows; Jetson cabinet with the PuP Pack (in this repository since 2026-10-10: [docs/pup/README.md](../pup/README.md); the pack itself from its author's zip or the private `pup_pack` submodule) |

## Where the Tron instance lives

| What | Where |
|---|---|
| Game repo (MPF + Godot) | this repository; built as stacked phase branches `phase2-machine` .. `phase11-hd` (PRs #2-#9), VPX bridge PR #10 |
| Asset/spec repo (ROM-derived) | `Ashram56/Tron-Legacy-LE-ROM-Decryption`, git submodule at `assets/`; its `AGENTS.md` points to agent A and keeps the Tron extraction notes |
| ROM | the game runs the LE rules on Pro (default) or LE hardware: [hardware.md](../hardware.md), "Pro or LE" |
| Coil times | the ROM's, generated into `game/config/rom/coil_times.yaml` from `assets/rom_data/io/coils.csv` |
| User docs | [README](../../README.md), [requirements.md](../requirements.md), [hardware.md](../hardware.md) (P-ROC), [vpx.md](../vpx.md) (Visual Pinball X), [development.md](../development.md), [performance.md](../performance.md) |
| Departures from the ROM | [rom_differences.md](../rom_differences.md): read before changing a rule; add every new departure there |

## A, ROM extraction

Done for Tron Legacy LE 1.74 (`trn_174h`) and ported to Pro 1.74 (`trn_17402`); this repo pins it as a
submodule and a sync job opens a "Sync assets to <sha>" PR when it moves (run setup, the render check and the
tests on it, then the owner merges).

## B, VPX extraction

Done on the VPW Mod v1.1 table: the layout is `game/monitor/` (`monitor.yaml`, playfield picture), started with
`python scripts/run.py --monitor`. The run's commands and expected counts (44 switches, 64 lamps, 8 flashers)
are the worked example in the agent file, "Checking a run".

## C, strict recreation

Built: phases 1-10 (PRs #1-#8), the hardware overlays (P-ROC, virtual + MPF Monitor, VPX), Pro/LE,
coin door and in-game service (PR #17). Open:

1. Trace kinds that still differ: the `TRACES` table in `tests/test_traces.py` is the work list (for
   example `bonus` and `zuse_fast_scoring` match on audits only; End of Line waits on Flynn's Arcade awards
   at the VUK, deff 83, leff 159).
2. The 11 newer reference traces in the asset repo's `rom_data/states/traces/` (multi-player, tilt and slam,
   match, Sea of Simulation stages 4-8) are not in `TRACES` yet (inferred from the table, check).
3. The Pro's own rules are not ported (the game runs LE 1.74 rules on Pro hardware; rom_differences.md).
4. Ramp tube wiring on the IO board: documentation PR #16 is open; tubes stay off on the P-ROC until checked
   with a logic analyzer (docs/hardware.md).
5. Real-machine checks only the owner can do: coil strengths on the P-ROC, tube sides, coin door input.

## D, VPX bridge

**The table in VPX on Windows**: **owner test, outcome not reported yet** (merged in PR #10, 2026-10-04). Start here: ask the owner for the result of the checklist in docs/vpx.md "To check on Windows" and `game\logs\vpx_bridge.log`.

Open:

1. **Owner test on Windows** (above): registration (as Administrator; pywin32 post-install if a DLL
   error), `.vbs` written, `run.py --hw vpx`, then the table: no message box, switches in MPF's console, 4 balls
   in the trough, coin/start, kick to the shooter lane, plunger, flippers, drain and tilt stop the flippers,
   flashers and lamps, ramp tube colours, drop target reset (sol 3), VUK (4), Recognizer and 3-bank motors
   (6, 23), orbit post (7), closing the table quits the game.
2. Only the owner can judge: flipper latency (fast flips should make it a non-issue; unverified), ball search,
   the trough, mechanisms (motors, moving targets).
3. GI is not driven by MPF; if the owner wants GI effects, map MPF's GI to the table's `GiCallback` strings.
4. The DMD shows in Godot's window, not the table's DMD: `--dmd-size 1280x320` and placing the window by hand;
   embedding it in the table (or B2S/FlexDMD) is not done.
5. MPF on another PC: `TRON_MPF_HOST` / `TRON_MPF_PORT`, and MPF's BCP server must listen on an outside address
   (unverified).

## E, improvements

Current defaults (`dmd_mode.gd` constants and `project.godot`): HD on, Tron blue text `#2a6cff`, glow
`#22b8ff` at 0.8, font Rajdhani Bold, text scale 0.85. Back to the ROM: `--dmd classic`, `--dmd-font rom`,
`--dmd-tint orange`, `--dmd-text-glow 0`. The operator can also set the text glow and size in the service
menu (ADJUSTMENTS > DISPLAY ADJUSTMENTS, persisted; FACTORY returns to the options).

### Owner decisions (keep adding)

| Date | Decision |
|---|---|
| 2026-10-04 | HD DMD in Tron blue, animations included; orange only as `--dmd-tint orange`. |
| 2026-10-04 | **No colourisation on `main`**, no colour option left in the public repo; colour work lives in the private repo only. |
| 2026-10-04 | Free play by default on the desktop (`--no-free-play` for coins). |
| 2026-10-06 | Clean font for HD text; Orbitron + glow tried as default, then Rajdhani default with glow 0.8; text scale 0.85 (the clean fonts looked bigger than the ROM's and stacked lines touched). |
| 2026-10-06 | Outlined ROM fonts sized and placed by their lit dots. |
| 2026-10-07 | ZUSE/TRON target letters stay the ROM's pictures, upscaled: the clean-font versions looked worse. |
| 2026-10-07 | Effects that are only frames and blocks drawn as sharp rectangles. |
| 2026-10-10 | Service menu DISPLAY ADJUSTMENTS: TEXT SIZE capped at 110% (above it stacked lines touch); TEXT GLOW OFF to 300%. |
| 2026-10-10 | PuP videos on Windows play through GDE GoZen with GPU decoding (Direct3D 11 Video), like Linux; the native video add-on (it stuttered) stays as the fallback. Built in the PuP fork ([Tron-Legacy-MPF-PuP](https://github.com/Ashram56/Tron-Legacy-MPF-PuP) PR #15). |
| 2026-10-10 | **PuP Pack merged into this repository** (the fork Tron-Legacy-MPF-PuP is history). Optional: the installers take the private `pup_pack` submodule only with a token or credentials that read it, else install the game alone; `--pup-zip` takes the author's zip. Godot 4.6.3 (the native video add-on needs 4.6), separate render thread on by default (`--no-render-thread`). Colourisation stays out of the public repo. |

### Ideas not built (ask before starting)

- New modes or rule changes (the owner has said they may come; nothing built yet: `rom_differences.md`
  says "No scoring or rules departures yet").
- A Tron-style font for the ZUSE/TRON letters (each sprite carries `metadata/letter` for it).
- Colour from the private repo's work, once the owner wants it public in some form (their call: rights).

## F, packaging

Built: `setup.py` and `run.py` on three OSes, the three installers with one-line install, the P-ROC build,
Docker, CI on three OSes. Open:

1. Port `-Vpx` / `-Table` from Transformers' Windows installer (packaging agent, section 4, step 4); `docs/vpx.md` then gives the
   one line.
2. A double-click launcher per platform (Windows shortcut or `.bat`, macOS `.command`) that runs `run.py` with
   the installed options: not built; the owner runs the command line today.
3. Transformers has only the Windows installer; macOS and Linux installers, Docker and CI are not ported.

## G, PuP Pack

Built (in the fork Tron-Legacy-MPF-PuP, merged here 2026-10-10): Terry Red's "End of Line" pack on backglass,
DMD and topper windows, OST in place of the ROM music, GoZen (Linux, Windows) and native_video (macOS) players,
Jetson hardware decoding: [docs/pup/README.md](../pup/README.md), [docs/jetson/README.md](../jetson/README.md),
[docs/performance.md](../performance.md). Open: after a display change, re-run `scripts/pup/pup_captures.py`
and fix the flagged rows of `game/tron_pup/trigger_map.yaml`.

## Owner preferences

Go ahead without asking for approval; pick a default, say which, and list what needs the owner's judgement as
a short numbered list. Small update zips of changed files only, never a full rebuild (A). Answer in the
owner's language (Vincent sometimes writes in French). CI runs only on pushes to `main`: test locally before
pushing a branch.

Last updated 2026-10-10 (PuP Pack merged in from the fork; DMD glow and size in the service menu; PuP video on Windows; agents and knowledge base moved to Stern-SAM-Decryption; this page keeps Tron's part).
