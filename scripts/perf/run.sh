#!/usr/bin/env bash
# One performance run (docs/performance.md): plays a scenario with the perf probe on, samples tegrastats (on a Jetson)
# and the per-thread CPU of Godot and MPF, then writes a one-page summary.
#
#   bash scripts/perf/run.sh SCENARIO [SECONDS] [NVPMODEL_MODE]     # one scenario (default 60 s)
#   bash scripts/perf/run.sh --suite [NVPMODEL_MODE]                # the trouble-spot clips in scripts/perf/clips.txt
#
# Output: perf/<date-time>-<label>/<scenario>/ (git-ignored): frames.csv, video.csv, av.csv, events.csv (the probe),
# threads.csv, tegrastats.log, godot.log, mpf.log, run.log and summary.md; with --suite also a suite.md over all
# clips. NVPMODEL_MODE switches the Jetson power mode for the run (sudo) and restores the previous one afterwards.
# Extra environment for run.py goes through as is (e.g. TRON_PUP=0); PERF_LABEL names the output folder.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
PY="$ROOT/.venv/bin/python"; [ -x "$PY" ] || PY=python3
export DISPLAY="${DISPLAY:-:0}"

SUITE=0
if [ "${1:-}" = --suite ]; then SUITE=1; shift; MODE="${1:-}"; else
    SCEN="${1:?usage: run.sh SCENARIO [SECONDS] [MODE] | run.sh --suite [MODE]}"; SECS="${2:-60}"; MODE="${3:-}"
fi
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="$ROOT/perf/$STAMP-${PERF_LABEL:-$([ "$SUITE" = 1 ] && echo suite || echo "$SCEN")}${MODE:+-mode$MODE}"
mkdir -p "$OUT"

OLD_MODE=""
if [ -n "$MODE" ] && command -v nvpmodel >/dev/null 2>&1; then
    OLD_MODE="$(sudo nvpmodel -q 2>/dev/null | sed -n '2p' | tr -d ' ')"
    printf 'no\nno\n' | sudo nvpmodel -m "$MODE" >/dev/null 2>&1
fi
restore_mode() {
    if [ -n "$OLD_MODE" ] && [ "$OLD_MODE" != "$MODE" ]; then printf 'no\nno\n' | sudo nvpmodel -m "$OLD_MODE" >/dev/null 2>&1; fi
}
trap restore_mode EXIT

one() {   # one SCENARIO SECONDS
    local d="$OUT/$1"
    mkdir -p "$d"
    {
        echo "scenario $1, $2 s, $(date -u +%FT%TZ), $(git -C "$ROOT" describe --always --dirty 2>/dev/null)"
        command -v nvpmodel >/dev/null 2>&1 && sudo nvpmodel -q 2>/dev/null | head -1
        [ -f /etc/nv_tegra_release ] && head -1 /etc/nv_tegra_release
        nproc
    } > "$d/run.log"
    local tpid=""
    if command -v tegrastats >/dev/null 2>&1; then
        sudo tegrastats --stop >/dev/null 2>&1 || true
        sudo tegrastats --interval 500 --logfile "$d/tegrastats.log" &
        tpid=$!
    fi
    "$PY" "$HERE/sampler.py" "$d" &
    local spid=$!
    ( cd "$ROOT" && TRON_PERF_DIR="$d" timeout -s INT "$(( $2 + 90 ))" "$PY" scripts/run.py --scenario "$1" --seconds "$2" \
        >> "$d/run.log" 2>&1 < /dev/null )
    echo "exit=$?" >> "$d/run.log"
    touch "$d/STOP"; wait "$spid" 2>/dev/null
    if [ -n "$tpid" ]; then sudo tegrastats --stop >/dev/null 2>&1 || true; sudo chown "$(id -u):$(id -g)" "$d/tegrastats.log" 2>/dev/null; fi
    cp "$ROOT/game/logs/godot.log" "$d/" 2>/dev/null
    cp "$(ls -t "$ROOT"/game/logs/*mpf*.log 2>/dev/null | head -1)" "$d/mpf.log" 2>/dev/null
    rm -f "$d/STOP"
    "$PY" "$HERE/summary.py" "$d"
}

if [ "$SUITE" = 1 ]; then
    while read -r scen secs; do
        case "$scen" in ''|'#'*) continue ;; esac
        one "$scen" "$secs"
    done < "$HERE/clips.txt"
    "$PY" "$HERE/summary.py" --suite "$OUT"
else
    one "$SCEN" "$SECS"
fi
echo "results: $OUT"
