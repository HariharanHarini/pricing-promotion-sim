#!/usr/bin/env python3
"""Step 10: regenerate twice with the same seed and compare row counts + checksums.

    python repro_check.py --skus 5000 --days 180 --promos 2000 --seed 20261022
"""
import argparse
import json
import shutil
import subprocess
import sys

ap = argparse.ArgumentParser()
ap.add_argument("--skus", type=int, default=5000)
ap.add_argument("--days", type=int, default=180)
ap.add_argument("--promos", type=int, default=2000)
ap.add_argument("--seed", type=int, default=20261022)
a = ap.parse_args()
runs = {}
for tag, seed in (("a", a.seed), ("b", a.seed), ("c", a.seed + 1)):
    out = f"out/repro_{tag}"
    shutil.rmtree(out, ignore_errors=True)
    subprocess.run([sys.executable, "generate.py", "--skus", str(a.skus), "--days", str(a.days), "--promos", str(a.promos),
                    "--seed", str(seed), "--out", out], check=True, stdout=subprocess.DEVNULL)
    runs[tag] = json.load(open(f"{out}/MANIFEST.json"))
    shutil.rmtree(out)
rows = []
ok = True
for f in runs["a"]:
    same = runs["a"][f] == runs["b"][f]
    diff_seed = runs["a"][f]["sha256"] != runs["c"][f]["sha256"]
    ok &= same
    rows.append((f, runs["a"][f]["rows"], runs["a"][f]["sha256"][:16], runs["b"][f]["sha256"][:16], "identical" if same else "DIFFERENT", "differs" if diff_seed else "same"))
md = [f"# Reproducibility report", "", f"Command: `python generate.py --skus {a.skus} --days {a.days} --promos {a.promos} --seed {a.seed}` run twice (A, B) plus once with seed {a.seed + 1} (C).", "",
      "| File | Rows | SHA-256 run A | SHA-256 run B | A vs B | A vs C (other seed) |", "|---|---|---|---|---|---|"]
md += [f"| {r[0]} | {r[1]:,} | {r[2]} | {r[3]} | {r[4]} | {r[5]} |" for r in rows]
md += ["", f"**Result: {'REPRODUCIBLE - all files byte-identical' if ok else 'NOT REPRODUCIBLE'}**"]
open("docs/reproducibility_report.md", "w").write("\n".join(md) + "\n")
print("\n".join(md[-3:]))
sys.exit(0 if ok else 1)
