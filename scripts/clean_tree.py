#!/usr/bin/env python3
"""Find and remove the empty folders a checkout collects over time.

    python scripts/clean_tree.py            # lists them
    python scripts/clean_tree.py --delete   # removes them

Git does not track folders: when a pull, a branch switch or an upstream sync moves or deletes files, the folders they
were in can stay behind, empty or holding only Python's __pycache__. This removes those, and nothing else: a folder
with any other file in it, a folder Git ignores (the venv, tools/, pup_media/, game/addons/, game/logs/, ...), the
submodules (assets/, pup_pack/) and .git/ are left alone, so it is safe to run at any time.
"""
import argparse
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import toolchain as tc  # noqa: E402

CACHE = "__pycache__"


def submodules(root):
    """Submodule paths from .gitmodules (relative, with / separators)."""
    paths = set()
    try:
        with open(os.path.join(root, ".gitmodules"), encoding="utf-8") as f:
            for line in f:
                key, _, value = line.partition("=")
                if key.strip() == "path":
                    paths.add(value.strip())
    except OSError:
        pass
    return paths


def ignored(root, rels):
    """The subset of rels (folders, relative) that .gitignore covers; none when git is missing."""
    if not rels:
        return set()
    try:
        out = subprocess.run(["git", "check-ignore", "--stdin"], cwd=root, input="\n".join(r + "/" for r in rels),
                             capture_output=True, text=True).stdout
    except OSError:
        return set(rels)  # without git, touch nothing
    return {line.rstrip("/") for line in out.splitlines() if line.strip()}


def leftovers(root=tc.ROOT):
    """Relative paths of the folders holding no file except in __pycache__, outermost first."""
    skip = submodules(root) | {".git"}
    tops = [d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)) and d not in skip]
    skip |= ignored(root, tops)  # .venv, tools/, pup_media/, ...: not walked
    walked = []  # (rel, subfolders, has files), parents before children
    for dirpath, dirnames, filenames in os.walk(root):
        rel = os.path.relpath(dirpath, root).replace(os.sep, "/")
        if rel == ".":
            dirnames[:] = [d for d in dirnames if d not in skip]
            continue
        walked.append((rel, list(dirnames), bool(filenames)))
    empty = {}  # rel -> nothing but empty folders and __pycache__ inside
    for rel, dirnames, files in reversed(walked):
        empty[rel] = os.path.basename(rel) == CACHE or (not files and all(empty[rel + "/" + d] for d in dirnames))
    found = []
    for rel in sorted(r for r, e in empty.items() if e):
        if os.path.basename(rel) == CACHE or any(rel.startswith(f + "/") for f in found):
            continue  # a cache next to real code stays; inside a leftover it goes with it
        found.append(rel)
    keep = ignored(root, found)
    return [r for r in found if r not in keep]


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--delete", action="store_true", help="remove the folders listed (default: only list them)")
    args = p.parse_args(argv)
    found = leftovers()
    for rel in found:
        if args.delete:
            shutil.rmtree(os.path.join(tc.ROOT, rel), ignore_errors=True)
        print(("removed " if args.delete else "") + rel)
    if not found:
        print("no empty folders")
    elif not args.delete:
        print("{} empty folder(s); python scripts/clean_tree.py --delete removes them".format(len(found)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
