#!/usr/bin/env python
"""Stage-1 eval with pi (https://github.com/earendil-works/pi) as harness.

Frames + question are fed to `pi -p` (print mode, no sandbox tools needed);
pi talks to the AMAP gateway via ~/.pi/agent/models.json.

Usage:
  python agent/eval_pi.py --limit 5          # smoke test
  python agent/eval_pi.py                    # full dev split
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import cv2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent.eval_baseline import load_samples
from agent.tools import BENCH_DIR

PROJ_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(PROJ_DIR, "outputs", "predictions")
PI_BIN = os.path.join(PROJ_DIR, "third_party", "pi-runtime",
                      "node_modules", ".bin", "pi")
PROVIDER = os.environ.get("VISTR_PI_PROVIDER", "amap-gateway")
MODEL = os.environ.get("VISTR_PI_MODEL", "qwen3-vl-plus")

PROMPT = """观察这些视频帧（按时间顺序），回答以下问题。

【题目】{question}
【选项】{options}

只输出最终答案（选项原文之一，不要解释）。"""


def _extract_frames(video_path, out_dir, n=8):
    cap = cv2.VideoCapture(video_path)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    paths = []
    for j in range(n):
        cap.set(cv2.CAP_PROP_POS_FRAMES, round(j * (total - 1) / max(n - 1, 1)))
        ok, fr = cap.read()
        if ok:
            fr = cv2.resize(fr, (640, 360))
            p = os.path.join(out_dir, f"frame_{j:02d}.jpg")
            cv2.imwrite(p, fr, [cv2.IMWRITE_JPEG_QUALITY, 65])
            paths.append(p)
    cap.release()
    return paths


def _parse_pi_json(stdout):
    """Extract thinking and final text from pi's JSON event stream."""
    thinking_deltas = []
    text_deltas = []
    final_thinking = None
    final_text = None
    usage = {}

    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        event_type = event.get("type")
        if event_type == "message_update":
            delta = event.get("assistantMessageEvent", {})
            delta_type = delta.get("type")
            if delta_type == "thinking_delta":
                thinking_deltas.append(delta.get("delta", ""))
            elif delta_type == "text_delta":
                text_deltas.append(delta.get("delta", ""))
        elif event_type == "message_end":
            message = event.get("message", {})
            blocks = message.get("content", []) if isinstance(message, dict) else []
            thinking = []
            text = []
            for block in blocks:
                if block.get("type") == "thinking":
                    thinking.append(block.get("thinking", ""))
                elif block.get("type") == "text":
                    text.append(block.get("text", ""))
            if thinking or text:
                final_thinking = "".join(thinking)
                final_text = "".join(text)
            usage = event.get("usage", usage)

    reasoning = final_thinking if final_thinking is not None else "".join(thinking_deltas)
    answer = final_text if final_text is not None else "".join(text_deltas)
    return reasoning.strip(), answer.strip(), usage


def solve_pi(sample, timeout=300):
    video_path = os.path.join(BENCH_DIR, sample["video"])
    question = sample["direct_prompting"]
    options = sample["options"]
    t0 = time.time()

    with tempfile.TemporaryDirectory(prefix="pi_eval_") as tmp:
        frames = _extract_frames(video_path, tmp, n=8)
        prompt = PROMPT.format(question=question, options=" / ".join(options))
        cmd = [PI_BIN, "-p", "--mode", "json", "--no-tools",
               "--provider", PROVIDER, "--model", MODEL]
        cmd += [f"@{p}" for p in frames]
        cmd.append(prompt)
        try:
            last_err = None
            for attempt in range(3):
                proc = subprocess.run(cmd, capture_output=True, text=True,
                                      timeout=timeout, cwd=tmp)
                if proc.returncode == 0:
                    break
                last_err = f"pi exit {proc.returncode}: {proc.stderr.strip()[:300]}"
                time.sleep(5 * (attempt + 1))
            else:
                raise RuntimeError(last_err)
            reasoning, final_answer, usage = _parse_pi_json(proc.stdout)
            answer = final_answer.strip("。.")
            pred = None
            for o in options:
                if o.lower() in answer.lower():
                    pred = o
                    break
            if pred is None:
                pred = answer
            return {
                "id": sample["id"], "task": sample["task"],
                "gt": sample["answer"], "pred": pred,
                "correct": pred == sample["answer"],
                "src": "pi_baseline",
                "question": question, "options": options,
                "video": sample.get("video", ""),
                "dimension": sample.get("dimension", ""),
                "reasoning": reasoning,
                "final_answer": final_answer,
                "raw_answer": answer[:500],
                "usage": usage,
                "elapsed_s": time.time() - t0,
                "model": MODEL,
            }
        except Exception as e:
            return {
                "id": sample["id"], "task": sample["task"],
                "gt": sample["answer"], "pred": None,
                "correct": False, "src": "error",
                "question": question, "options": options,
                "reasoning": "", "final_answer": "",
                "error": f"{type(e).__name__}: {str(e)[:300]}",
                "model": MODEL,
            }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", default="dev", choices=["dev", "eval", "all"])
    parser.add_argument("--tasks", type=str, default="")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--per-task", type=int, default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--output", type=str, default="")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()

    tasks_filter = [t.strip() for t in args.tasks.split(",") if t.strip()] or None
    samples = load_samples(args.split, tasks_filter, args.limit, per_task=args.per_task)
    print(f"Harness: pi ({PI_BIN})")
    print(f"Model: {PROVIDER}/{MODEL}")
    print(f"Loaded {len(samples)} samples (split={args.split}, tasks={tasks_filter})")

    if not args.output:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = os.path.join(OUTPUT_DIR, f"pi_{MODEL}_{ts}.jsonl")
    os.makedirs(os.path.dirname(args.output), exist_ok=True)

    done_ids = set()
    if args.resume and os.path.exists(args.output):
        kept = []
        with open(args.output) as f:
            for line in f:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if r.get("src") == "error":
                    continue
                kept.append(line)
                done_ids.add(r["id"])
        with open(args.output, "w") as f:
            f.writelines(kept)
        print(f"Resuming: {len(done_ids)} done (error rows dropped for rerun)")

    remaining = [s for s in samples if s["id"] not in done_ids]
    print(f"Running {len(remaining)} samples")

    t0 = time.time()
    results = []
    lock = threading.Lock()
    counter = [0]

    with open(args.output, "a") as fout:
        def run_one(sample):
            result = solve_pi(sample, timeout=args.timeout)
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
    print(f"Model: {PROVIDER}/{MODEL} via pi")
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
