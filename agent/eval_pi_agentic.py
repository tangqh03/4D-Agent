#!/usr/bin/env python
"""Stage-2 eval: pi with native tools, workspace as the agent's world.

Each sample gets a temp workspace containing a copy of the source video.
pi runs with its full default toolset; the VLM extracts/inspects frames
itself (bash + read) and answers with a `FINAL: <option>` line.

Usage:
  python agent/eval_pi_agentic.py --limit 3          # smoke test
  python agent/eval_pi_agentic.py --workers 4        # full dev split
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent.eval_baseline import load_samples
from agent.tools import BENCH_DIR

PROJ_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(PROJ_DIR, "outputs", "predictions")
PI_BIN = os.path.join(PROJ_DIR, "third_party", "pi-runtime",
                      "node_modules", ".bin", "pi")
PROVIDER = os.environ.get("VISTR_PI_PROVIDER", "amap-gateway")
MODEL = os.environ.get("VISTR_PI_MODEL", "qwen3-vl-plus")

PROMPT = """你是视频时空推理专家。当前工作目录下有一个源视频 `video.mp4`（本目录可自由读写）。

可用手段：
- bash 工具：`ffmpeg`/`ffprobe` 已装；`/opt/conda/bin/python` 带 cv2/numpy，可抽帧、算光流、差分、裁剪放大等
- read 工具：可直接查看图片文件（jpg/png），看抽出的帧

任务：先用工具分析视频（建议先 ffprobe 看时长帧率，再按需抽帧查看；关键区域可裁剪放大），然后回答：

【题目】{question}
【选项】{options}

要求：分析完成后，最后单独一行输出你的答案，格式：
FINAL: <选项原文之一>"""


def parse_final(text, options):
    for line in reversed(text.strip().splitlines()):
        m = re.match(r"\s*FINAL[:：]\s*(.+)", line.strip(), re.IGNORECASE)
        if m:
            cand = m.group(1).strip().strip("。.**`")
            for o in options:
                if o.lower() == cand.lower() or o.lower() in cand.lower():
                    return o
            return cand
    tail = text[-300:].lower()
    for o in options:
        if o.lower() in tail:
            return o
    return None


def solve_agentic(sample, timeout=600):
    video_path = os.path.join(BENCH_DIR, sample["video"])
    question = sample["direct_prompting"]
    options = sample["options"]
    t0 = time.time()

    with tempfile.TemporaryDirectory(prefix="pi_ws_") as ws:
        shutil.copy(video_path, os.path.join(ws, "video.mp4"))
        prompt = PROMPT.format(question=question, options=" / ".join(options))
        cmd = [PI_BIN, "-p", "--provider", PROVIDER, "--model", MODEL, prompt]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=timeout, cwd=ws)
            out = proc.stdout.strip()
            if proc.returncode != 0:
                raise RuntimeError(
                    f"pi exit {proc.returncode}: {proc.stderr.strip()[:300]}")
            pred = parse_final(out, options)
            return {
                "id": sample["id"], "task": sample["task"],
                "gt": sample["answer"], "pred": pred,
                "correct": pred == sample["answer"],
                "src": "pi_agentic",
                "question": question, "options": options,
                "video": sample.get("video", ""),
                "dimension": sample.get("dimension", ""),
                "raw_answer": out[-800:],
                "elapsed_s": time.time() - t0,
                "model": MODEL,
            }
        except Exception as e:
            return {
                "id": sample["id"], "task": sample["task"],
                "gt": sample["answer"], "pred": None,
                "correct": False, "src": "error",
                "question": question, "options": options,
                "error": f"{type(e).__name__}: {str(e)[:300]}",
                "elapsed_s": time.time() - t0,
                "model": MODEL,
            }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", default="dev", choices=["dev", "eval", "all"])
    parser.add_argument("--tasks", type=str, default="")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--output", type=str, default="")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()

    tasks_filter = [t.strip() for t in args.tasks.split(",") if t.strip()] or None
    samples = load_samples(args.split, tasks_filter, args.limit)
    print(f"Harness: pi agentic ({PI_BIN})")
    print(f"Model: {PROVIDER}/{MODEL}")
    print(f"Loaded {len(samples)} samples (split={args.split}, tasks={tasks_filter})")

    if not args.output:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = os.path.join(OUTPUT_DIR, f"pi_agentic_{MODEL}_{ts}.jsonl")
    os.makedirs(os.path.dirname(args.output), exist_ok=True)

    done_ids = set()
    if args.resume and os.path.exists(args.output):
        with open(args.output) as f:
            for line in f:
                try:
                    done_ids.add(json.loads(line)["id"])
                except (json.JSONDecodeError, KeyError):
                    pass
        print(f"Resuming: {len(done_ids)} already done")

    remaining = [s for s in samples if s["id"] not in done_ids]
    print(f"Running {len(remaining)} samples")

    t0 = time.time()
    results = []
    lock = threading.Lock()
    counter = [0]

    with open(args.output, "a") as fout:
        def run_one(sample):
            result = solve_agentic(sample, timeout=args.timeout)
            with lock:
                results.append(result)
                fout.write(json.dumps(result, ensure_ascii=False) + "\n")
                fout.flush()
                counter[0] += 1
                ok = "✓" if result["correct"] else "✗"
                print(f"[{counter[0]}/{len(remaining)}] {ok} "
                      f"{result['task']}[{result['id']}] pred={result['pred']} "
                      f"elapsed={result.get('elapsed_s', 0):.1f}s", flush=True)

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            list(pool.map(run_one, remaining))

    elapsed = time.time() - t0
    correct = sum(1 for r in results if r["correct"])
    total = len(results)
    print(f"\n{'='*50}")
    print(f"Model: {PROVIDER}/{MODEL} via pi agentic")
    print(f"Results: {correct}/{total} = {correct/max(total,1)*100:.1f}%")
    print(f"Time: {elapsed:.0f}s ({elapsed/max(total,1):.1f}s/sample)")

    by_task = {}
    for r in results:
        by_task.setdefault(r["task"], [0, 0])
        by_task[r["task"]][1] += 1
        if r["correct"]:
            by_task[r["task"]][0] += 1
    print(f"\nPer-task:")
    for task in sorted(by_task):
        c, t = by_task[task]
        print(f"  {task}: {c}/{t} = {c/t*100:.0f}%")


if __name__ == "__main__":
    main()
