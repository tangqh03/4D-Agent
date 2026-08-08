#!/usr/bin/env python
"""Small-scale grounding comparison: semantic_crop vs read_crop (self-grounding).

For a fixed set of (video, time, target) probes drawn from ViSTR tasks, ask pi
to zoom into the target region using ONE designated tool, then extract the
crop images from the session so a human can audit first-hit quality.

Usage:
  VISTR_PI_EXTENSION=... /opt/conda/bin/python scripts/grounding_probe.py --tool semantic_crop
  VISTR_PI_EXTENSION=... /opt/conda/bin/python scripts/grounding_probe.py --tool read_crop
"""
from __future__ import annotations

import argparse
import base64
import glob
import json
import os
import shutil
import subprocess
import tempfile
import time

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PI_BIN = os.path.join(PROJ, "third_party", "pi-runtime", "node_modules", ".bin", "pi")
BENCH = os.path.join(PROJ, "data", "benchmarks", "ViSTR-Bench-Public")
EXT = os.environ.get("VISTR_PI_EXTENSION",
                     os.path.join(PROJ, "agent", "pi_ext", "vistr_video_tools.ts"))
OUT = os.path.join(PROJ, "outputs", "grounding_probe")

# (sample_id, rel video, time_s, english target) — task-agnostic probes:
# object references only, no question semantics.
PROBES = [
    (1, "data/Outcome_Prediction/Basketball_Shot/Ego4D", 2.5, "the basketball rim and net"),
    (150, "data/Physical_Dynamics/Jenga_Stability/Video", 1.9, "the hand touching the wooden block tower"),
    (114, "data/Motion_Perception/Relative_Velocity", 0.5, "the car inside the green box"),
    (670, "data/Outcome_Prediction/Swimming_Race", 2.0, "the swimmer closest to the wall"),
    (26, "data/Outcome_Prediction/Billiards_Shot", 1.0, "the white cue ball on the table"),
]


def resolve_video(sample_id):
    data = json.load(open(os.path.join(BENCH, "data.json")))
    for s in data:
        if s["id"] == sample_id:
            return os.path.join(BENCH, s["video"])
    raise KeyError(sample_id)


def run_probe(tool, sample_id, time_s, target, outdir):
    video = resolve_video(sample_id)
    with tempfile.TemporaryDirectory(prefix="probe_") as ws:
        shutil.copy(video, os.path.join(ws, "video.mp4"))
        prompt = (f"当前目录有 video.mp4。请只使用 {tool} 工具(可多次调用直到裁到目标),"
                  f"查看 t={time_s}s 时刻的这个目标: \"{target}\"。"
                  f"裁到后回答: 最终用了几次调用,以及你在裁剪图里看到了什么(一句话)。")
        t0 = time.time()
        proc = subprocess.run([PI_BIN, "-p", "--provider", "amap-gateway",
                               "--model", "qwen3-vl-plus", "-e", EXT, prompt],
                              capture_output=True, text=True, timeout=600, cwd=ws)
        elapsed = time.time() - t0
    # harvest session: count tool calls, dump crop images
    sess = sorted(glob.glob(os.path.expanduser(
        "~/.pi/agent/sessions/*probe_*/*.jsonl")), key=os.path.getmtime)
    calls = 0
    imgs = 0
    if sess:
        for line in open(sess[-1]):
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("type") != "message":
                continue
            c = e["message"].get("content")
            if not isinstance(c, list):
                continue
            for p in c:
                if p.get("type") == "toolCall" and p.get("name") == tool:
                    calls += 1
                if p.get("type") == "image":
                    imgs += 1
                    with open(os.path.join(
                            outdir, f"{tool}_{sample_id}_img{imgs:02d}.jpg"), "wb") as f:
                        f.write(base64.b64decode(p["data"]))
    return {"id": sample_id, "target": target, "tool": tool,
            "calls": calls, "images": imgs, "elapsed_s": round(elapsed, 1),
            "answer": proc.stdout.strip()[-300:]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tool", required=True,
                        choices=["semantic_crop", "read_crop"])
    args = parser.parse_args()
    outdir = os.path.join(OUT, args.tool)
    os.makedirs(outdir, exist_ok=True)
    results = []
    for sid, _, t, target in PROBES:
        print(f"--- probe {sid}: {target}", flush=True)
        try:
            r = run_probe(args.tool, sid, t, target, outdir)
        except Exception as e:
            r = {"id": sid, "tool": args.tool, "error": str(e)[:200]}
        print(json.dumps(r, ensure_ascii=False), flush=True)
        results.append(r)
    with open(os.path.join(OUT, f"{args.tool}_results.json"), "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    ok = [r for r in results if "calls" in r]
    print(f"\n{args.tool}: mean calls {sum(r['calls'] for r in ok)/max(len(ok),1):.1f}, "
          f"mean {sum(r['elapsed_s'] for r in ok)/max(len(ok),1):.0f}s")


if __name__ == "__main__":
    main()
