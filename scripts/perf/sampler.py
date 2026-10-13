#!/usr/bin/env python3
"""Per-thread CPU sampler for a performance run (docs/performance.md): every second, the CPU % of each thread of the
Godot and MPF processes (from /proc/<pid>/task/*/stat), until the file STOP appears in OUT or the processes end.

    python scripts/perf/sampler.py OUT_DIR

Writes OUT_DIR/threads.csv: t_s,process,tid,thread,cpu_pct (100 = one core), and OUT_DIR/processes.csv:
t_s,process,rss_mb,hwm_mb (resident memory now and its peak, from /proc/<pid>/status). Linux only.
"""
import os
import sys
import time

# by executable: Godot's binary name, and MPF's console script as the Python interpreter's first argument
PATTERNS = {"godot": lambda argv: os.path.basename(argv[0]).startswith("Godot_v"),
            "mpf": lambda argv: len(argv) > 1 and os.path.basename(argv[1]) == "mpf"}


def find_pids():
    pids = {}
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open("/proc/%s/cmdline" % pid, "rb") as f:
                argv = f.read().decode(errors="replace").split("\0")
        except OSError:
            continue
        for name, match in PATTERNS.items():
            if name not in pids and argv[0] and match(argv):
                pids[name] = int(pid)
    return pids


def thread_ticks(pid):
    out = {}
    try:
        tids = os.listdir("/proc/%d/task" % pid)
    except OSError:
        return out
    for tid in tids:
        try:
            with open("/proc/%d/task/%s/stat" % (pid, tid)) as f:
                stat = f.read()
        except OSError:
            continue
        name = stat[stat.index("(") + 1:stat.rindex(")")]
        fields = stat[stat.rindex(")") + 2:].split()
        out[int(tid)] = (name, int(fields[11]) + int(fields[12]))     # utime + stime
    return out


def memory_mb(pid):
    """VmRSS and VmHWM of a process, in MB (None when it is gone)."""
    out = {}
    try:
        with open("/proc/%d/status" % pid) as f:
            for line in f:
                if line.startswith(("VmRSS:", "VmHWM:")):
                    out[line.split(":")[0]] = int(line.split()[1]) / 1024.0
    except OSError:
        return None
    return out.get("VmRSS"), out.get("VmHWM")


def main(out_dir):
    hz = os.sysconf("SC_CLK_TCK")
    stop = os.path.join(out_dir, "STOP")
    t0 = time.time()
    prev = {}
    with open(os.path.join(out_dir, "threads.csv"), "w") as f, open(os.path.join(out_dir, "processes.csv"), "w") as fm:
        f.write("t_s,process,tid,thread,cpu_pct\n")
        fm.write("t_s,process,rss_mb,hwm_mb\n")
        while not os.path.exists(stop):
            pids = find_pids()
            now = time.time()
            for proc, pid in pids.items():
                for tid, (name, ticks) in thread_ticks(pid).items():
                    if tid == pid:
                        name += " (main)"
                    key = (proc, tid)
                    if key in prev:
                        t_prev, ticks_prev = prev[key]
                        pct = 100.0 * (ticks - ticks_prev) / hz / max(now - t_prev, 1e-3)
                        if pct > 0.0:
                            f.write("%.1f,%s,%d,%s,%.1f\n" % (now - t0, proc, tid, name.replace(",", " "), pct))
                    prev[key] = (now, ticks)
                mem = memory_mb(pid)
                if mem and mem[0] is not None:
                    fm.write("%.1f,%s,%.1f,%.1f\n" % (now - t0, proc, mem[0], mem[1] or 0.0))
            f.flush()
            fm.flush()
            time.sleep(1.0)


if __name__ == "__main__":
    main(sys.argv[1])
