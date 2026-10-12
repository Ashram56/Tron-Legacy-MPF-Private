#!/usr/bin/env python3
"""One-page summary of a performance run (docs/performance.md).

    python scripts/perf/summary.py RUN_DIR            # RUN_DIR/summary.md (and printed)
    python scripts/perf/summary.py --suite OUT_DIR    # OUT_DIR/suite.md: one line per clip of a --suite run

Reads the probe's frames.csv, video.csv, av.csv and events.csv, threads.csv (sampler.py), tegrastats.log, mpf.log and
godot.log. The first STARTUP_S seconds (window creation, first video opens) are reported apart from the rest.
"""
import csv
import os
import re
import statistics
import sys

STARTUP_S = 8.0
VBLANK_MS = 1000.0 / 60.0
STALL_MS = 300.0
# Godot errors known to be harmless, counted apart (docs/upstream_issues/godot-separate-render-thread-glyph-cache.md)
KNOWN_ERRORS = (('Condition "p_image.is_null() || p_image->is_empty()" is true', "glyph cache, separate render thread"),)
TARGETS = (   # acceptance (docs/performance.md): key, limit, what
    ("long_frames", 0, "frames over 2 vblanks after start-up"),
    ("video_skipped", 0, "video frames skipped"),
    ("av_avg_ms", 40, "A/V drift average (ms)"),
    ("black", 0, "black screens over 0.2 s"),
    ("errors", 0, "Godot ERROR lines"),
)


def rows(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def pct(values, p):
    if not values:
        return None
    s = sorted(values)
    return s[min(len(s) - 1, int(len(s) * p))]


def frames(d):
    fr = [(float(r["t_ms"]), float(r["delta_ms"]), float(r["draw_ms"]) if r.get("draw_ms") else None)
          for r in rows(os.path.join(d, "frames.csv")) if r.get("delta_ms")]   # the last line can be cut short
    if len(fr) < 10:
        return {}
    stalls, prev = [], None
    for t, _, _ in fr:
        if prev is not None and t - prev > STALL_MS:
            stalls.append((prev / 1000.0, (t - prev) / 1000.0))
        prev = t
    run = [(t, dt, dr) for t, dt, dr in fr if t >= STARTUP_S * 1000.0]
    ts = [t for t, _, _ in run]
    # frame times from the timestamps: Godot's process delta can read one vblank for a frame held much longer
    dts = [b - a for a, b in zip(ts, ts[1:])] or [dt for _, dt, _ in run]
    draws = [dr for _, _, dr in run if dr is not None]
    dur = (ts[-1] - ts[0]) / 1000.0 if len(ts) > 1 else 1.0
    per_s = {}
    for t in ts:
        per_s[int(t // 1000)] = per_s.get(int(t // 1000), 0) + 1
    full = sorted(per_s.items())[1:-1] or sorted(per_s.items())
    return {
        "seconds": round(dur),
        "fps_avg": len(dts) / dur,
        "fps_min": min(v for _, v in full),
        "median_ms": statistics.median(dts),
        "p99_ms": pct(dts, 0.99),
        "max_ms": max(dts),
        "long_frames": sum(1 for x in dts if x > 2.5 * VBLANK_MS),   # held 3 vblanks or more (timestamps jitter)
        "over_100": sum(1 for x in dts if x > 100.0),
        "draw_median_ms": statistics.median(draws) if draws else None,
        "draw_p99_ms": pct(draws, 0.99),
        "stalls": stalls,
    }


def video(d):
    vr = rows(os.path.join(d, "video.csv"))
    by = {}
    for r in vr:
        s = by.setdefault(r["screen"], {"shown": 0, "skipped": 0, "late": []})
        s["shown"] += 1
        step = int(r["step"])
        if 1 < step <= 120:
            s["skipped"] += step - 1
        s["late"].append(float(r["late_ms"]))
    av = [abs(float(r["av_ms"])) for r in rows(os.path.join(d, "av.csv"))]
    ev = rows(os.path.join(d, "events.csv"))
    opens = [r for r in ev if r["kind"] == "open"]
    burst = {}
    for r in opens:
        burst.setdefault(int(float(r["t_ms"]) // 500), set()).add(r["screen"])
    return {
        "screens": by,
        "video_skipped": sum(s["skipped"] for s in by.values()),
        "late_p95_ms": pct([x for s in by.values() for x in s["late"]], 0.95),
        "av_avg_ms": statistics.mean(av) if av else 0.0,
        "av_max_ms": max(av) if av else 0.0,
        "opens": len(opens),
        "bursts": ["%.1f s: screens %s" % (k / 2.0, "+".join(sorted(v))) for k, v in sorted(burst.items()) if len(v) >= 3],
        "black": sum(1 for r in ev if r["kind"] == "black"),
        "black_detail": ["%.1f s screen %s %s" % (float(r["t_ms"]) / 1000, r["screen"], r["detail"])
                         for r in ev if r["kind"] == "black"],
    }


def deff_delays(d):
    """MPF asks for a display effect (tron_deff_N) -> the media controller reports its slide created."""
    req, out = {}, []
    path = os.path.join(d, "mpf.log")
    if not os.path.exists(path):
        return out
    pat = re.compile(r"\S+ (\d+):(\d+):(\d+),(\d+) .*Event: ======'(?:tron_deff_(\d+)|slide_deff_(\d+)_created)'")
    for line in open(path, errors="replace"):
        m = pat.match(line)
        if not m:
            continue
        t = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4)) / 1000.0
        if m.group(5):
            req.setdefault(int(m.group(5)), t)
        elif int(m.group(6)) in req:
            out.append((t - req.pop(int(m.group(6))), int(m.group(6))))
    return sorted(out, reverse=True)


def tegra(d):
    path = os.path.join(d, "tegrastats.log")
    if not os.path.exists(path):
        return {}
    cpu, peak, gpu, vin, temp, dec, n = [], 0, [], [], [], 0, 0
    for line in open(path, errors="replace"):
        m = re.search(r"CPU \[([^\]]*)\]", line)
        if not m:
            continue
        n += 1
        loads = [int(x.split("%")[0]) for x in m.group(1).split(",") if "%" in x]
        if loads:
            cpu.append(sum(loads) / len(loads))
            peak = max(peak, max(loads))
        m = re.search(r"GR3D_FREQ (\d+)%", line)
        gpu += [int(m.group(1))] if m else []
        m = re.search(r"VDD_IN (\d+)mW", line)
        vin += [int(m.group(1))] if m else []
        m = re.search(r"CPU@([\d.]+)C", line)
        temp += [float(m.group(1))] if m else []
        dec += 1 if re.search(r"NVDEC \d", line) else 0
    return {"cpu_avg": statistics.mean(cpu) if cpu else None, "cpu_peak_core": peak,
            "gpu_avg": statistics.mean(gpu) if gpu else None, "w_avg": statistics.mean(vin) / 1000 if vin else None,
            "w_peak": max(vin) / 1000 if vin else None, "temp_max": max(temp) if temp else None,
            "nvdec_clock_on": 100.0 * dec / n if n else None}


def threads(d):
    tr = rows(os.path.join(d, "threads.csv"))
    acc = {}
    for r in tr:
        k = (r["process"], r["tid"], r["thread"])
        acc.setdefault(k, []).append(float(r["cpu_pct"]))
    if not tr:
        return []
    secs = max(float(r["t_s"]) for r in tr) or 1.0
    top = sorted(((sum(v) / secs, max(v), k) for k, v in acc.items()), reverse=True)
    return top[:8]


def godot_errors(d):
    """ERROR lines of godot.log: (unexpected count, {known error: count})."""
    errs, known = 0, {}
    path = os.path.join(d, "godot.log")
    if os.path.exists(path):
        for line in open(path, errors="replace"):
            if not line.startswith("ERROR"):
                continue
            k = next((name for text, name in KNOWN_ERRORS if text in line), None)
            if k:
                known[k] = known.get(k, 0) + 1
            else:
                errs += 1
    return errs, known


def memory(d):
    """Godot's memory at start-up (10 s), after the effects preload (godot.log) and at its peak; board RAM."""
    out = {}
    pm = [r for r in rows(os.path.join(d, "processes.csv")) if r["process"] == "godot"]
    if pm:
        rss = [(float(r["t_s"]), float(r["rss_mb"])) for r in pm]
        out["rss_start"] = next((m for t, m in rss if t >= 10.0), rss[-1][1])
        out["rss_peak"] = max(m for _, m in rss)
        out["rss_end"] = rss[-1][1]
        out["hwm"] = max(float(r["hwm_mb"]) for r in pm)
    gm = rows(os.path.join(d, "memory.csv"))
    if gm:
        out["static_peak"] = max(float(r["static_mb"]) for r in gm)
        out["video_peak"] = max(float(r["video_mb"]) for r in gm)
        out["texture_peak"] = max(float(r["texture_mb"]) for r in gm)
    path = os.path.join(d, "godot.log")
    if os.path.exists(path):
        m = re.search(r"DMD: (\d+) .*preloaded(?: in ([\d.]+) s)?", open(path, errors="replace").read())
        if m:
            out["preloaded"] = int(m.group(1))
            out["preload_s"] = float(m.group(2)) if m.group(2) else None
    path = os.path.join(d, "tegrastats.log")
    if os.path.exists(path):
        ram = [int(x) for x in re.findall(r"RAM (\d+)/", open(path, errors="replace").read())]
        swap = [int(x) for x in re.findall(r"SWAP (\d+)/", open(path, errors="replace").read())]
        if ram:
            out["ram_avg"], out["ram_max"] = statistics.mean(ram), max(ram)
            out["swap_max"] = max(swap) if swap else 0
    return out


def summarize(d):
    f, v, t = frames(d), video(d), tegra(d)
    errs, known = godot_errors(d)
    vals = {"long_frames": f.get("long_frames", 0), "video_skipped": v["video_skipped"], "av_avg_ms": v["av_avg_ms"],
            "black": v["black"], "errors": errs}
    name = os.path.basename(os.path.normpath(d))
    head = open(os.path.join(d, "run.log")).readline().strip() if os.path.exists(os.path.join(d, "run.log")) else ""
    L = ["# %s" % name, "", head, ""]
    if f:
        L.append("**Frames** (after the first %.0f s, %d s): %.1f FPS avg, worst second %d, median %.2f ms, p99 %.1f ms, "
                 "max %.0f ms; %d frames over 2 vblanks, %d over 100 ms. Main thread to draw submitted: median %s ms, "
                 "p99 %s ms." % (STARTUP_S, f["seconds"], f["fps_avg"], f["fps_min"], f["median_ms"], f["p99_ms"],
                                 f["max_ms"], f["long_frames"], f["over_100"],
                                 "%.1f" % f["draw_median_ms"] if f["draw_median_ms"] is not None else "-",
                                 "%.1f" % f["draw_p99_ms"] if f["draw_p99_ms"] is not None else "-"))
        L.append("")
        L.append("**Stalls** over %.0f ms (start s: length s): %s" % (
            STALL_MS, ", ".join("%.1f: %.2f" % s for s in f["stalls"]) or "none"))
    L.append("")
    L.append("**Video**: %d opens; %d frames skipped; late p95 %s ms; A/V drift avg %.0f ms, max %.0f ms; black %d %s" % (
        v["opens"], v["video_skipped"], "%.0f" % v["late_p95_ms"] if v["late_p95_ms"] is not None else "-",
        v["av_avg_ms"], v["av_max_ms"], v["black"], "; ".join(v["black_detail"])))
    for s, st in sorted(v["screens"].items()):
        L.append("- screen %s: %d shown, %d skipped" % (s, st["shown"], st["skipped"]))
    L.append("- screens switching together (3+ within 0.5 s): %s" % (", ".join(v["bursts"]) or "none"))
    dd = deff_delays(d)
    L.append("")
    L.append("**Slowest display effects** (MPF request to slide created): %s" % (
        ", ".join("deff %d %.2f s" % (n, s) for s, n in dd[:6]) or "-"))
    if t:
        L.append("")
        L.append("**Board** (tegrastats): CPU %.0f%% avg (one core peaked at %d%%), GPU %.0f%%, %.1f W avg / %.1f W peak, "
                 "CPU %.1f C max; video decoder clock on in %.0f%% of samples (clock, not load)." % (
                     t["cpu_avg"], t["cpu_peak_core"], t["gpu_avg"] or 0, t["w_avg"] or 0, t["w_peak"] or 0,
                     t["temp_max"] or 0, t["nvdec_clock_on"] or 0))
    mem = memory(d)
    if mem:
        parts = []
        if "rss_start" in mem:
            parts.append("Godot resident %.0f MB at 10 s, %.0f MB at the end, %.0f MB peak" % (
                mem["rss_start"], mem["rss_end"], max(mem["rss_peak"], mem["hwm"])))
        if "video_peak" in mem:
            parts.append("Godot video memory peak %.0f MB (textures %.0f MB), static %.0f MB" % (
                mem["video_peak"], mem["texture_peak"], mem["static_peak"]))
        if "preloaded" in mem:
            parts.append("effects preload: %d resources%s" % (
                mem["preloaded"], " in %.1f s" % mem["preload_s"] if mem.get("preload_s") else ""))
        if "ram_avg" in mem:
            parts.append("board RAM used %.0f MB avg, %.0f MB max, swap %d MB max" % (
                mem["ram_avg"], mem["ram_max"], mem["swap_max"]))
        L.append("")
        L.append("**Memory**: " + "; ".join(parts) + ".")
    th = threads(d)
    if th:
        L.append("")
        L.append("**Threads** (CPU % of one core, average / peak): " + ", ".join(
            "%s %s %.0f/%.0f" % (k[0], k[2], a, m) for a, m, k in th))
    if known:
        L.append("")
        L.append("**Known harmless Godot errors** (not counted below): " + ", ".join(
            "%s %d" % (k, n) for k, n in sorted(known.items())))
    L.append("")
    L.append("**Targets**: " + "; ".join("%s %s (%s %s)" % (
        "PASS" if vals[k] <= lim else "FAIL", what, "%.0f" % vals[k] if isinstance(vals[k], float) else vals[k],
        "<= %s" % lim) for k, lim, what in TARGETS))
    text = "\n".join(L) + "\n"
    open(os.path.join(d, "summary.md"), "w").write(text)
    return text, f, v, vals


def suite(out):
    lines = ["# Suite %s" % os.path.basename(os.path.normpath(out)), "",
             "| clip | FPS avg | worst s | p99 ms | >2 vblank | >100 ms | longest stall s | video skipped | A/V avg ms "
             "| black | errors | slowest deff |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for name in sorted(os.listdir(out)):
        d = os.path.join(out, name)
        if not os.path.isdir(d):
            continue
        _, f, v, vals = summarize(d)
        dd = deff_delays(d)
        lines.append("| %s | %.1f | %d | %.1f | %d | %d | %.2f | %d | %.0f | %d | %d | %s |" % (
            name, f.get("fps_avg", 0), f.get("fps_min", 0), f.get("p99_ms", 0), f.get("long_frames", 0),
            f.get("over_100", 0), max([s for _, s in f.get("stalls", [])] or [0]), v["video_skipped"],
            v["av_avg_ms"], v["black"], vals["errors"], "deff %d %.2f s" % (dd[0][1], dd[0][0]) if dd else "-"))
    text = "\n".join(lines) + "\n"
    open(os.path.join(out, "suite.md"), "w").write(text)
    print(text)


if __name__ == "__main__":
    if sys.argv[1] == "--suite":
        suite(sys.argv[2])
    else:
        print(summarize(sys.argv[1])[0])
