"""scripts/perf/summary.py on a synthetic run (docs/performance.md)."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "perf"))
import summary  # noqa: E402


class TestPerfSummary(unittest.TestCase):

    def run_dir(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        t, lines = 0.0, ["t_ms,delta_ms,draw_ms"]
        for i in range(30 * 60):                    # 30 s at 60 FPS, with one 500 ms stall at 20 s
            dt = 500.0 if i == 20 * 60 else 1000.0 / 60
            t += dt
            lines.append("%.1f,%.3f,%.3f" % (t, dt, 5.0))
        open(os.path.join(d, "frames.csv"), "w").write("\n".join(lines) + "\n")
        open(os.path.join(d, "video.csv"), "w").write(
            "t_ms,screen,file,frame,step,late_ms\n10000,2,a.mp4,1,1,0\n10033,2,a.mp4,2,1,1\n10133,2,a.mp4,5,3,2\n")
        open(os.path.join(d, "av.csv"), "w").write("t_ms,screen,file,av_ms\n11000,2,a.mp4,30\n12000,2,a.mp4,-50\n")
        open(os.path.join(d, "events.csv"), "w").write(
            "t_ms,kind,screen,detail\n100,open,2,a.mp4\n120,open,12,b.mp4\n300,open,13,c.mp4\n5000,black,2,250 ms\n")
        open(os.path.join(d, "mpf.log"), "w").write(
            "2026-10-09 13:01:16,341 : INFO : EventManager : Event: ======'tron_deff_85'====== Args={}\n"
            "2026-10-09 13:01:17,319 : INFO : EventManager : Event: ======'slide_deff_085_created'====== Args={}\n")
        open(os.path.join(d, "godot.log"), "w").write(
            "ERROR: something\nfine\nDMD: 1575 effect frames and scenes preloaded in 10.5 s\n"
            'ERROR: Condition "p_image.is_null() || p_image->is_empty()" is true.\n')
        open(os.path.join(d, "processes.csv"), "w").write(
            "t_s,process,rss_mb,hwm_mb\n5.0,godot,900.0,900.0\n10.0,godot,1000.0,1000.0\n20.0,godot,1400.0,1500.0\n"
            "30.0,godot,1300.0,1500.0\n30.0,mpf,200.0,210.0\n")
        open(os.path.join(d, "memory.csv"), "w").write(
            "t_ms,static_mb,video_mb,texture_mb\n1000,100.0,300.0,200.0\n2000,110.0,380.0,270.0\n")
        open(os.path.join(d, "tegrastats.log"), "w").write(
            "".join("10-09-2026 18:50:5%d RAM %d/6834MB (lfb 19x4MB) SWAP %d/3417MB (cached 0MB) CPU [20%%@1904,52%%@1911,"
                    "15%%@1905,51%%@1906,off,off] EMC_FREQ 2%%@1600 GR3D_FREQ 0%%@[408] VIC_FREQ 115 APE 150 AUX@40C "
                    "CPU@41.5C thermal@40.65C AO@41.5C GPU@40C PMIC@50C VDD_IN 5422mW/5258mW\n" % (i, ram, swap)
                    for i, ram, swap in ((0, 2700, 0), (1, 2900, 2))))
        return d

    def test_summary(self):
        d = self.run_dir()
        text, f, v, vals = summary.summarize(d)
        self.assertAlmostEqual(60.0, f["fps_avg"], delta=2.0)
        self.assertEqual([(20.0, 0.5)], [(round(s, 0), round(n, 2)) for s, n in f["stalls"]])
        self.assertEqual(1, f["long_frames"])
        self.assertEqual(2, v["video_skipped"])
        self.assertEqual(40.0, v["av_avg_ms"])
        self.assertEqual(["0.0 s: screens 12+13+2"], v["bursts"])
        self.assertEqual(1, v["black"])
        self.assertEqual(1, vals["errors"])          # the known glyph-cache error is counted apart
        self.assertIn("glyph cache, separate render thread 1", text)
        self.assertIn("deff 85 0.98 s", text)
        self.assertIn("FAIL video frames skipped", text)
        self.assertIn("**Memory**: Godot resident 1000 MB at 10 s, 1300 MB at the end, 1500 MB peak; Godot video "
                      "memory peak 380 MB (textures 270 MB), static 110 MB; effects preload: 1575 resources in 10.5 s; "
                      "board RAM used 2800 MB avg, 2900 MB max, swap 2 MB max.", text)
        self.assertTrue(os.path.exists(os.path.join(d, "summary.md")))

    def test_held_frame_counted_from_timestamps(self):
        d = self.run_dir()
        lines = open(os.path.join(d, "frames.csv")).read().splitlines()
        t, out = 0.0, [lines[0]]
        for i in range(30 * 60):                    # one frame held 433 ms at 15 s whose process delta reads 16.7 ms
            t += 433.0 if i == 15 * 60 else 1000.0 / 60
            out.append("%.1f,%.3f,%.3f" % (t, 1000.0 / 60, 5.0))
        open(os.path.join(d, "frames.csv"), "w").write("\n".join(out) + "\n")
        f = summary.frames(d)
        self.assertEqual(1, f["long_frames"])
        self.assertEqual(1, f["over_100"])
        self.assertAlmostEqual(433.0, f["max_ms"], delta=0.5)
        self.assertEqual([(15.0, 0.43)], [(round(s, 0), round(n, 2)) for s, n in f["stalls"]])


if __name__ == "__main__":
    unittest.main()
