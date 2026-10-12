# One-line installer: findings

What running the one-line install commands (README, "Install") taught us, for the core game only. The fixes
were made and tested in the PuP fork's copy of `scripts/install/`, which was merged back into this repository
on 2026-10-10 with the PuP Pack and the Jetson video decoding.

Last updated 2026-10-08.

## The commands

| OS | Line |
|---|---|
| Windows | `powershell -ExecutionPolicy Bypass -Command "& ([scriptblock]::Create((irm https://raw.githubusercontent.com/Ashram56/Tron-Legacy-MPF/main/scripts/install/install_prereqs_windows.ps1) -join [char]10))"` (was `irm ... \| iex`, which failed on Windows PowerShell with "the terminator #> is missing": observed on Transformers, 2026-10-10) |
| macOS | `bash <(curl -fsSL https://raw.githubusercontent.com/Ashram56/Tron-Legacy-MPF/main/scripts/install/install_prereqs_macos.sh)` |
| Linux | `bash <(curl -fsSL https://raw.githubusercontent.com/Ashram56/Tron-Legacy-MPF/main/scripts/install/install_prereqs_linux.sh)` |

Environment variables read before the line:

- `TRON_DIR`: install folder (default `~/Tron-Legacy-MPF`, `%USERPROFILE%\Tron-Legacy-MPF`; keep it out of OneDrive).
- `TRON_BRANCH`, `TRON_REPO`: branch and repository to clone. A folder that already holds a clone is updated
  with `git pull --ff-only`, so the line is safe to run again.
- `TRON_GITHUB_TOKEN`: token for private repositories, so the installer does not prompt.

Put the token in front of the line rather than typing it at the prompt:

```sh
TRON_GITHUB_TOKEN=github_pat_... bash <(curl -fsSL https://raw.githubusercontent.com/Ashram56/Tron-Legacy-MPF/main/scripts/install/install_prereqs_linux.sh)
```

Windows: `$env:TRON_GITHUB_TOKEN = "github_pat_..."` first, then the line.

## Private repositories and the GitHub token

The one-liner itself only works when this repository is public: `curl`/`irm` get a 404 for a private repository's
raw file. With a private repository, clone first (README, "Clone first"). The token step then covers the clone
and the assets submodule.

The first version of the token step wrote one token into git's `url.insteadOf` for all of `https://github.com/`
and checked it against the assets repository only. Testing found these problems (fixed in
`scripts/install/install_prereqs_{linux,macos}.sh` and `install_prereqs_windows.ps1`):

1. **Token only for the private repositories.** A token that cannot read a public repository (a fine-grained token
   scoped to other repositories, an expired one) made git fail on that public repository, because the
   `insteadOf` rewrote every GitHub URL. Fix: test each repository anonymously first, list the private ones,
   and put the token only into their URLs (`GIT_CONFIG_KEY_n = url.https://x-access-token:TOKEN@<repo>.insteadOf`,
   one per private repository). `setup.py` inherits these through the environment.
2. **Check every private repository** with `git ls-remote` after setting the token, not just the assets one, and
   name the one that fails. The prompt also lists which repositories are private.
3. **Clean the pasted token.** A token copied from an editor can carry spaces or a line break: strip all
   whitespace before using it. Then print its length and prefix (`github_pat_` about 93 characters,
   `ghp_` 40), never the token, so a truncated paste is obvious.
4. **Windows: paste with a right-click.** Ctrl+V does not paste into the hidden `Read-Host` prompt in every
   console; the prompt says to right-click.
5. **Windows: no credential pop-up.** Git Credential Manager opened its login window during the access test
   (and GitHub then refuses a password for git). Set `GCM_INTERACTIVE=never` next to `GIT_TERMINAL_PROMPT=0`
   during the test.
6. **Windows PowerShell 5.1 and stderr.** With `$ErrorActionPreference = 'Stop'`, a redirected native command's
   stderr (`fatal: could not read Username`) becomes a terminating error. Set it to `'Continue'` around the git
   calls and judge by the exit code only.
7. **Windows: Git on the PATH.** When Git is found only at its install folder (for example just installed), the
   current session's PATH does not have it, and `setup.py` (which runs `git` for the submodules) failed. Fix: add
   Git's folder to `$env:Path` for the session.

## Linux, Python and the venv

- **apt-cache and pipefail**: under `set -o pipefail`, `apt-cache ... | grep -q` fails when `grep` exits
  early and `apt-cache` gets SIGPIPE. Capture the output in a variable first, then test it.
- **Python 3.11 order**: the distribution's package, else the deadsnakes PPA on Ubuntu, else a
  standalone build from uv (no compiler, nothing system-wide; also the only route on Arch).
- **deadsnakes failure must fall back to uv**: `set -e` is off inside a function called with `||`,
  so a failed `add-apt-repository` went on, and on Ubuntu 22.04 apt then installed the distribution's own
  `python3.11` (a 3.11.0 release candidate). Fix: `|| return 1` after `add-apt-repository`, then `apt-get update`
  and check that the PPA's python3.11 is now offered, else return 1 so uv takes over.
- **Dead `.venv` is remade** (`scripts/setup.py`): when the Python a `.venv` was made from is removed
  or replaced (a deadsnakes or uv interpreter swapped), `.venv/bin/python` is a broken link and setup failed.
  Fix: if the venv folder exists but its python does not, run `python -m venv --clear`.
- **MPF Monitor on Linux arm64** (`scripts/toolchain.py`): PyQt6 6.8 and later ship arm64 wheels for
  glibc 2.39+ only (Ubuntu 24.04). On older systems (JetPack 5: glibc 2.31, JetPack 6: 2.35) pip falls back to the
  source package, which needs qmake and fails. Fix: add `PyQt6>=6.4.2,<6.8` for `linux`/`aarch64` to
  `MONITOR_REQUIREMENTS`, and leave the monitor out (with a note) when glibc is older than 2.28.
- **libdecor on Ubuntu 20.04**: `libdecor-0-0` (Wayland window decorations, optional for Godot) does
  not exist in 20.04 / JetPack 5. Skip it there instead of failing the apt step.

## Jetson boards

The core game runs on a Jetson (Ubuntu for arm64) with the Linux line above, given the arm64 items in the section
before (MPF Monitor needs the PyQt6 pin). What the Jetson work adds beyond that (NVIDIA hardware video decoding, L4T package pinning,
several video windows) is for PuP videos: [jetson/README.md](jetson/README.md).
