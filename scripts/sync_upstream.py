#!/usr/bin/env python3
"""Merge the latest upstream MPF game (Ashram56/Tron-Legacy-MPF) into this repository and re-check the PuP.

    python scripts/sync_upstream.py                      # fetch + merge upstream/main, then checks
    python scripts/sync_upstream.py --branch NAME        # another upstream branch
    python scripts/sync_upstream.py --no-merge           # only the checks (after a manual merge)

The PuP lives in its own files (game/pup/, game/tron_pup/, game/pup.cfg, game/config/pup.yaml,
game/modes/pup/, scripts/*pup*), so a merge only meets four one-line hooks in upstream files:
game/config/config.yaml (include pup.yaml), game/project.godot (the Pup autoload), .gitmodules (pup_pack) and
.gitignore. After the merge: the submodules, the generated config and media, the capture match
(scripts/pup_captures.py: does trigger_map.yaml still point at the effects that draw each PuP capture?) and
the unit tests. The merge is left uncommitted when it conflicts; nothing is pushed.
"""
import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import toolchain as tc  # noqa: E402

UPSTREAM = "https://github.com/Ashram56/Tron-Legacy-MPF.git"


def git(*args, check=True):
    print("$ git " + " ".join(args), flush=True)
    return subprocess.run(["git"] + list(args), cwd=tc.ROOT, check=check)


def step(cmd):
    print("$ " + " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=tc.ROOT).returncode


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--branch", default="main", help="upstream branch to merge (default main)")
    p.add_argument("--no-merge", action="store_true", help="skip fetch and merge, run the checks")
    args = p.parse_args(argv)
    if not args.no_merge:
        remotes = subprocess.run(["git", "remote"], cwd=tc.ROOT, capture_output=True, text=True).stdout.split()
        if "upstream" not in remotes:
            git("remote", "add", "upstream", UPSTREAM)
        git("fetch", "upstream", args.branch)
        if git("merge", "--no-edit", "upstream/" + args.branch, check=False).returncode:
            print("\nThe merge conflicts: resolve it (keep the PuP hook lines), commit, then run "
                  "`python scripts/sync_upstream.py --no-merge`.")
            return 1
    env = dict(os.environ, GIT_LFS_SKIP_SMUDGE="1")
    print("$ git submodule update --init --depth 1", flush=True)
    subprocess.run(["git", "submodule", "update", "--init", "--depth", "1"], cwd=tc.ROOT, env=env, check=True)
    failed = []
    for name, cmd in (("setup (new requirements, generated config and media, PuP media, Godot import)",
                       lambda: [sys.executable, "scripts/setup.py"]),
                      ("PuP capture match", lambda: [tc.python(), "scripts/pup_captures.py"]),
                      ("unit tests", lambda: [tc.python(), "-m", "pytest", "-q", "tests"])):
        # tc.python() is resolved per step: on a fresh clone the venv only exists once setup has run.
        if step(cmd()):
            failed.append(name)
    if failed:
        print("\nTo look at: " + ", ".join(failed) + (" (docs/pup_captures.md lists the captures to check)"
                                                      if "PuP capture match" in failed else ""))
        return 1
    print("\nUp to date with upstream/{}; the PuP map still matches.".format(args.branch))
    return 0


if __name__ == "__main__":
    sys.exit(main())
