#!/usr/bin/env bash
# Installs what this workspace needs on macOS (12 or newer, Intel or Apple silicon) and is missing, then runs
# scripts/setup.py. Safe to re-run.
#
#   scripts/install/install_prereqs_macos.sh                 # Python 3.11 + Git, then setup.py
#   scripts/install/install_prereqs_macos.sh --no-monitor    # ... without MPF Monitor (installed by default)
#   scripts/install/install_prereqs_macos.sh --proc          # ... plus libpinproc/pypinproc (needs Homebrew)
#   scripts/install/install_prereqs_macos.sh --dry-run       # print the plan, change nothing
#   scripts/install/install_prereqs_macos.sh --pup-zip PACK.zip # the PuP Pack from its author's zip (file or URL)
#   scripts/install/install_prereqs_macos.sh -- --skip-media # arguments after -- go to setup.py
#
# Options: --yes (no questions), --no-setup (prerequisites only), --python-org (use the python.org installer
# even when Homebrew is there). With Homebrew: `brew install python@3.11 git`. Without it: the python.org
# 3.11 installer (universal2 .pkg, needs an admin password) and Git from the Xcode Command Line Tools.
set -euo pipefail

# Run from a clone, it sets up that clone. Run on its own (fetched with curl, README "Install"), it first
# clones the repository into $TRON_DIR (default ~/Tron-Legacy-MPF-Private), branch $TRON_BRANCH (default main),
# from $TRON_REPO; an existing clone there gets a git pull.
SRC="${BASH_SOURCE[0]:-}"
if [ -n "$SRC" ] && [ -f "$(dirname "$SRC")/../setup.py" ]; then
    ROOT="$(cd "$(dirname "$SRC")/../.." && pwd)" CLONE=0
else
    ROOT="${TRON_DIR:-$HOME/Tron-Legacy-MPF-Private}" CLONE=1
fi
REPO_URL="${TRON_REPO:-https://github.com/Ashram56/Tron-Legacy-MPF-Private.git}"
REPO_BRANCH="${TRON_BRANCH:-main}"
HERE="$ROOT/scripts/install"
# The last Python 3.11 release with a macOS installer (later 3.11 releases are source-only security fixes)
PYORG_VERSION="3.11.9"
PYORG_PKG="python-${PYORG_VERSION}-macos11.pkg"
PYORG_URL="https://www.python.org/ftp/python/${PYORG_VERSION}/${PYORG_PKG}"
PYORG_PY="/Library/Frameworks/Python.framework/Versions/3.11/bin/python3.11"

DRY=0 YES=0 MONITOR=1 PROC=0 SETUP=1 PYORG=0
SETUP_ARGS=()

usage() { sed -n '2,14p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run) DRY=1 ;;
        -y|--yes) YES=1 ;;
        --monitor) MONITOR=1 ;;
        --no-monitor) MONITOR=0 ;;
        --proc) PROC=1 ;;
        --no-setup) SETUP=0 ;;
        --python-org) PYORG=1 ;;
        --pup-zip) [ $# -ge 2 ] || { echo "--pup-zip needs a zip file or URL" >&2; exit 2; }
                   TRON_PUP_ZIP="$2"; shift ;;
        -h|--help) usage; exit 0 ;;
        --) shift; SETUP_ARGS=("$@"); break ;;
        *) echo "unknown option: $1 (see --help)" >&2; exit 2 ;;
    esac
    shift
done

# The PuP Pack from a zip (--pup-zip, or TRON_PUP_ZIP in the environment): the pack as its author publishes
# it, instead of the pup_pack submodule (no access to that repository needed). setup.py extracts it.
TRON_PUP_ZIP="${TRON_PUP_ZIP:-}"
if [ -n "$TRON_PUP_ZIP" ]; then
    case "$TRON_PUP_ZIP" in
        http://*|https://*) ;;
        *) [ -f "$TRON_PUP_ZIP" ] || { echo "PuP Pack zip not found: $TRON_PUP_ZIP" >&2; exit 2; }
           TRON_PUP_ZIP="$(cd "$(dirname "$TRON_PUP_ZIP")" && pwd)/$(basename "$TRON_PUP_ZIP")" ;;
    esac
    export TRON_PUP_ZIP
fi

say() { printf '\n==> %s\n' "$*"; }
note() { printf '    %s\n' "$*"; }
die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }
run() {
    printf '    $ %s\n' "$*"
    if [ "$DRY" = 0 ]; then "$@"; fi
}

# ------------------------------------------------------------------ GitHub access (private repositories)
# The game repository or its assets submodule may be private: git then needs a GitHub token instead of a
# password. Give it as TRON_GITHUB_TOKEN (or GITHUB_TOKEN / GH_TOKEN), or paste it when asked. It is used for
# this run only (git's url.insteadOf in the environment, inherited by setup.py), and handed to git's
# credential helper, if one is set up (the macOS keychain, for example), so later `git pull`s work too.
ASSETS_URL="${TRON_ASSETS_REPO:-https://github.com/Ashram56/Tron-Legacy-LE-ROM-Decryption.git}"
PUP_URL="${TRON_PUP_REPO:-https://github.com/Ashram56/Tron-LE-PuP-Pack.git}"   # the pup_pack submodule (optional, docs/pup/README.md)
TOKEN="${TRON_GITHUB_TOKEN:-${GITHUB_TOKEN:-${GH_TOKEN:-}}}"

public_repo() { GIT_TERMINAL_PROMPT=0 GIT_ASKPASS=true git -c credential.helper= ls-remote "$1" HEAD >/dev/null 2>&1; }

github_auth() {
    AUTH_DONE=1
    say "GitHub access"
    if [ "$DRY" = 1 ]; then
        note "(dry run) a private repository asks for a GitHub token here$([ -n "$TOKEN" ] && echo ': using the one given')"
        return
    fi
    # only the repositories nobody can read without a login need the token: a token that cannot read a public
    # repository (a fine-grained one for other repositories, an expired one) would make git fail on it
    local url private=()
    for url in "$REPO_URL" "$ASSETS_URL"; do public_repo "$url" || private+=("$url"); done
    # the PuP Pack (optional): a zip replaces the pup_pack submodule; its private repository needs a token given
    # up front or credentials git already has, else the game installs without the pack (no prompt for it)
    if [ -z "$TRON_PUP_ZIP" ] && ! public_repo "$PUP_URL"; then
        if [ -n "$TOKEN" ]; then
            private+=("$PUP_URL")
        elif ! GIT_TERMINAL_PROMPT=0 git ls-remote "$PUP_URL" HEAD >/dev/null 2>&1; then
            note "PuP Pack: $PUP_URL is private; installing without it (--pup-zip PACK.zip adds it, docs/pup/README.md)"
        fi
    fi
    if [ ${#private[@]} = 0 ]; then
        note "the repositories are public: no token needed"
        return
    fi
    if [ -z "$TOKEN" ]; then
        local readable=1
        for url in "${private[@]}"; do GIT_TERMINAL_PROMPT=0 git ls-remote "$url" HEAD >/dev/null 2>&1 || readable=0; done
        if [ "$readable" = 1 ]; then
            note "a private repository, readable with the GitHub credentials git already has"
            return
        fi
        [ "$YES" = 0 ] && [ -r /dev/tty ] || die "a repository is private: set TRON_GITHUB_TOKEN to a GitHub token that can read it"
        note "Private: ${private[*]}"
        note "Paste a GitHub token that can read it (github.com > Settings > Developer settings > Personal access"
        note "tokens; a fine-grained token with Contents: read-only on these repositories)."
        printf '    token (not shown): ' >/dev/tty
        IFS= read -rs TOKEN </dev/tty
        printf '\n' >/dev/tty
    fi
    # a token copied from a text editor can carry spaces or a line break; GitHub tokens have none
    TOKEN="$(printf '%s' "$TOKEN" | tr -d '[:space:]')"
    [ -n "$TOKEN" ] || die "no token given"
    local prefix=unknown
    case "$TOKEN" in github_pat_*) prefix=github_pat_ ;; gh?_*) prefix="${TOKEN:0:4}" ;; esac
    note "token: ${#TOKEN} characters, type $prefix (a fine-grained token is about 93, a classic one 40)"
    # the token goes into the private repositories' URLs only (git's url.insteadOf, inherited by setup.py)
    local i=0
    for url in "${private[@]}"; do
        export "GIT_CONFIG_KEY_$i=url.https://x-access-token:${TOKEN}@${url#https://}.insteadOf" "GIT_CONFIG_VALUE_$i=$url"
        i=$((i + 1))
    done
    export GIT_CONFIG_COUNT=$i
    for url in "${private[@]}"; do
        GIT_TERMINAL_PROMPT=0 git ls-remote "$url" HEAD >/dev/null 2>&1 \
            || die "the GitHub token cannot read $url (check its repository access and expiry)"
    done
    printf 'protocol=https\nhost=github.com\nusername=x-access-token\npassword=%s\n\n' "$TOKEN" \
        | git credential approve 2>/dev/null || true
    note "token accepted"
}

# first thing, so a token is asked before the long installs (later, once git is installed, if it is missing)
AUTH_DONE=0
# (/usr/bin/git is only a stub until the Command Line Tools are installed: calling it opens their installer)
GIT_PATH="$(command -v git 2>/dev/null || true)"
if [ -n "$GIT_PATH" ] && { [ "$GIT_PATH" != /usr/bin/git ] || xcode-select -p >/dev/null 2>&1; }; then github_auth; fi

have_tool() { command -v "$1" >/dev/null 2>&1; }
confirm() {
    if [ "$DRY" = 0 ] && [ "$YES" = 0 ] && [ -t 0 ]; then
        local answer
        read -r -p "    $1 [Y/n] " answer
        case "$answer" in [nN]*) die "cancelled" ;; esac
    fi
}

if [ "$(uname -s)" != Darwin ]; then
    [ "$DRY" = 1 ] || die "this script is for macOS (Linux: install_prereqs_linux.sh)"
    note "not macOS: showing the plan only"
fi

MACOS="$(sw_vers -productVersion 2>/dev/null || echo unknown)"
say "Tron Legacy MPF prerequisites on macOS $MACOS ($(uname -m))$([ "$DRY" = 1 ] && echo ', dry run')"
case "$MACOS" in
    10.*|11.*) note "warning: macOS 12 or newer is needed (Godot 4.6, current Python and Qt builds)" ;;
esac

BREW=""
for b in brew /opt/homebrew/bin/brew /usr/local/bin/brew; do
    if have_tool "$b"; then BREW="$(command -v "$b")"; break; fi
done
if [ -n "$BREW" ] && [ "$PYORG" = 0 ]; then note "Homebrew: $BREW"; else note "Homebrew: not used"; fi

python_ok() { "$1" -c "import sys, venv, ensurepip; sys.exit(0 if sys.version_info[:2] == (3, 11) else 1)" >/dev/null 2>&1; }

find_python() {
    local c
    for c in python3.11 /opt/homebrew/bin/python3.11 /usr/local/bin/python3.11 "$PYORG_PY"; do
        if have_tool "$c" && python_ok "$(command -v "$c")"; then command -v "$c"; return 0; fi
    done
    return 1
}

brew_install() {    # brew_install FORMULA...: the ones that are not installed
    local missing=() f
    for f in "$@"; do
        "$BREW" list --formula "$f" >/dev/null 2>&1 || missing+=("$f")
    done
    if [ ${#missing[@]} = 0 ]; then note "in place: $*"; return 0; fi
    confirm "brew install ${missing[*]}?"
    run "$BREW" install "${missing[@]}"
}

# ------------------------------------------------------------------ Git

say "Git"
if have_tool git && git --version >/dev/null 2>&1; then
    note "in place: $(git --version)"
elif [ -n "$BREW" ]; then
    brew_install git
else
    # /usr/bin/git is a stub until the Command Line Tools are installed; this opens Apple's installer
    run xcode-select --install || true
    die "finish the Command Line Tools install that macOS just opened, then run this script again"
fi

# ------------------------------------------------------------------ Python 3.11

say "Python 3.11"
PY=""
if PY="$(find_python)"; then
    note "in place: $PY"
elif [ -n "$BREW" ] && [ "$PYORG" = 0 ]; then
    brew_install python@3.11
    PY="$("$BREW" --prefix python@3.11 2>/dev/null || echo /opt/homebrew/opt/python@3.11)/bin/python3.11"
else
    note "python.org installer $PYORG_VERSION (universal2): $PYORG_URL"
    confirm "Download and install it (asks for an admin password)?"
    TMP="$(mktemp -d)"
    run curl -fSL -o "$TMP/$PYORG_PKG" "$PYORG_URL"
    run sudo installer -pkg "$TMP/$PYORG_PKG" -target /
    # python.org builds bring no CA certificates of their own; this installs certifi's
    run "/Applications/Python 3.11/Install Certificates.command"
    rm -rf "$TMP"
    PY="$PYORG_PY"
fi
if [ "$DRY" = 0 ]; then
    python_ok "$PY" || die "no usable Python 3.11 at $PY (see the messages above)"
fi
note "Python: $PY"

# ------------------------------------------------------------------ P-ROC build tools

if [ "$PROC" = 1 ]; then
    say "P-ROC build tools (Homebrew)"
    [ -n "$BREW" ] || die "--proc needs Homebrew (https://brew.sh) for cmake, libusb, libusb-compat and libftdi"
    brew_install cmake pkg-config libusb libusb-compat libftdi
fi

[ "$AUTH_DONE" = 1 ] || github_auth    # git was missing at the start

# ------------------------------------------------------------------ repository (run on its own: clone it)

# Before a pull: files the update adds that are already here, untracked, would stop `git pull` ("untracked
# working tree files would be overwritten"). Godot writes a .uid next to every script it opens, so a new
# script's .uid is often on disk before the commit that adds it. Remove those, and any copy identical to the
# update's; move anything else aside as <file>.local so nothing of the player's is lost.
clear_untracked_in_update() {
    local up f
    up="$(git -C "$ROOT" rev-parse -q --verify '@{u}' 2>/dev/null)" || return 0
    while IFS= read -r -d '' f; do
        [ -e "$ROOT/$f" ] || [ -L "$ROOT/$f" ] || continue
        git -C "$ROOT" ls-files --error-unmatch -- "$f" >/dev/null 2>&1 && continue
        case "$f" in
            *.uid|*.import) run rm -f -- "$ROOT/$f" ;;
            *)  if [ -f "$ROOT/$f" ] && [ "$(git -C "$ROOT" hash-object -- "$f")" = "$(git -C "$ROOT" rev-parse "$up:$f")" ]; then
                    run rm -f -- "$ROOT/$f"
                else
                    note "kept your copy of $f as $f.local (the update adds its own)"
                    run mv -- "$ROOT/$f" "$ROOT/$f.local"
                fi ;;
        esac
    done < <(git -C "$ROOT" diff -z --name-only --no-renames --diff-filter=A HEAD "$up" --)
}

if [ "$CLONE" = 1 ]; then
    say "Repository: $REPO_URL ($REPO_BRANCH) in $ROOT"
    if [ -d "$ROOT/.git" ]; then
        # an existing clone: update its branch, or move to $REPO_BRANCH when that branch is gone from GitHub
        # (a deleted pull-request branch) or none is checked out
        CUR="$(git -C "$ROOT" symbolic-ref --short -q HEAD 2>/dev/null || true)"
        if [ -n "$CUR" ] && git -C "$ROOT" ls-remote --exit-code --heads origin "$CUR" >/dev/null 2>&1; then
            run git -C "$ROOT" fetch origin
            clear_untracked_in_update
            run git -C "$ROOT" pull --ff-only
        else
            note "branch '${CUR:-none}' is no longer on GitHub: switching to $REPO_BRANCH"
            run git -C "$ROOT" fetch --prune origin
            run git -C "$ROOT" checkout -B "$REPO_BRANCH" --track "origin/$REPO_BRANCH"
        fi
    else
        run git clone --branch "$REPO_BRANCH" "$REPO_URL" "$ROOT"
    fi
fi

# ------------------------------------------------------------------ workspace

if [ "$SETUP" = 1 ]; then
    say "Workspace (scripts/setup.py)"
    ARGS=()
    [ "$MONITOR" = 1 ] || ARGS+=(--no-monitor)
    [ "$DRY" = 1 ] && ARGS+=(--dry-run)
    ARGS+=(${SETUP_ARGS[@]+"${SETUP_ARGS[@]}"})
    if [ "$DRY" = 1 ] && ! have_tool "$PY"; then
        note "\$ $PY $ROOT/scripts/setup.py ${ARGS[*]-}"
    else
        run "$PY" "$ROOT/scripts/setup.py" ${ARGS[@]+"${ARGS[@]}"}
    fi
fi

if [ "$PROC" = 1 ]; then
    say "P-ROC: libpinproc + pypinproc"
    BUILD=("$HERE/build_pinproc.sh" --python "$ROOT/.venv/bin/python" --prefix "$("$BREW" --prefix 2>/dev/null || echo /usr/local)")
    [ "$DRY" = 1 ] && BUILD+=(--dry-run)
    if [ "$DRY" = 1 ]; then printf '    $ %s\n' "${BUILD[*]}"; else "${BUILD[@]}"; fi
    note "If macOS claims the P-ROC as /dev/tty.usbserial*, install FTDI's D2xxHelper and reboot (docs/requirements.md)."
fi

say "Done$([ "$DRY" = 1 ] && echo ' (dry run: nothing was changed)')"
if [ "$SETUP" = 1 ]; then
    note "In $ROOT:"
    note "Start the game:  .venv/bin/python scripts/run.py$([ "$MONITOR" = 1 ] && echo ' --monitor')"
    note "Run the tests:   .venv/bin/python -m pytest -q tests"
fi
