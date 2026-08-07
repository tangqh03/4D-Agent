#!/usr/bin/env python
"""Baseline eval: direct VLM prompting (frames + question → answer).

Usage:
  python agent/eval_baseline.py --limit 5                    # smoke test
  python agent/eval_baseline.py                              # full dev
  VISTR_LLM_MODEL=qwen3-vl-8b-thinking python agent/eval_baseline.py
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from datetime import datetime

import cv2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent import llm
from agent.tools import BENCH_DIR

PROJ_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_PATH = os.path.join(PROJ_DIR, "data", "benchmarks", "ViSTR-Bench-Public", "data.json")
SPLIT_PATH = os.path.join(PROJ_DIR, "configs", "split.json")
OUTPUT_DIR = os.path.join(PROJ_DIR, "outputs", "predictions")

BASELINE_PROMPT = """观察这些视频帧（按时间顺序），回答以下问题。

【题目】{question}
【选项】{options}

只输出最终答案（选项原文之一，不要解释）。"""


def _frames_b64(video_path, n=8):
    cap = cv2.VideoCapture(video_path)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    out = []
    for j in range(n):
        cap.set(cv2.CAP_PROP_POS_FRAMES, round(j * (total - 1) / max(n - 1, 1)))
        ok, fr = cap.read()
        if ok:
            fr = cv2.resize(fr, (640, 360))
            out.append(base64.b64encode(
                cv2.imencode(".jpg", fr, [cv2.IMWRITE_JPEG_QUALITY, 65])[1]).decode())
    cap.release()
    return out


def load_samples(split="dev", tasks=None, limit=None):
    with open(DATA_PATH) as f:
        data = json.load(f)
    with open(SPLIT_PATH) as f:
        split_cfg = json.load(f)
    data_by_id = {s["id"]: s for s in data}
    if split == "all":
        samples = data
    else:
        ids = []
        for task_ids in split_cfg.values():
            ids.extend(task_ids.get(split, []))
        samples = [data_by_id[i] for i in ids if i in data_by_id]
    if tasks:
        samples = [s for s in samples if s["task"] in tasks]
    if limit:
        samples = samples[:limit]
    return samples


def solve_baseline(sample, max_tokens=100, timeout=180):
    video_path = os.path.join(BENCH_DIR, sample["video"])
    question = sample["direct_prompting"]
    options = sample["options"]

    t0 = time.time()
    frames = _frames_b64(video_path, n=8)
    prompt = BASELINE_PROMPT.format(
        question=question, options=" / ".join(options))
    content = [{"type": "text", "text": prompt}]
    for b in frames:
        content.append({"type": "image_url",
                        "image_url": {"url": "data:image/jpeg;base64," + b}})

    try:
        resp = llm.chat([{"role": "user", "content": content}],
                        max_tokens=max_tokens, temperature=0.0, timeout=timeout,
                        retries=3)
        final_answer = (resp.get("content") or "").strip()
        answer = final_answer.strip("。.")
        reasoning = resp.get("reasoning") or ""
        pred = None
        for o in options:
            if o.lower() in answer.lower():
                pred = o
                break
        if pred is None:
            pred = answer
        elapsed = time.time() - t0
        return {
            "id": sample["id"], "task": sample["task"],
            "gt": sample["answer"], "pred": pred,
            "correct": pred == sample["answer"],
            "src": "baseline_direct",
            "question": question, "options": options,
            "video": sample.get("video", ""),
            "dimension": sample.get("dimension", ""),
            "reasoning": reasoning,
            "final_answer": final_answer,
            "raw_answer": answer,
            "usage": resp.get("usage", {}),
            "elapsed_s": elapsed,
            "model": llm.MODEL,
        }
    except Exception as e:
        return {
            "id": sample["id"], "task": sample["task"],
            "gt": sample["answer"], "pred": None,
            "correct": False, "src": "error",
            "question": question, "options": options,
            "reasoning": "", "final_answer": "",
            "error": f"{type(e).__name__}: {str(e)[:300]}",
            "model": llm.MODEL,
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", default="dev", choices=["dev", "eval", "all"])
    parser.add_argument("--tasks", type=str, default="")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--output", type=str, default="")
    parser.add_argument("--max-tokens", type=int, default=100)
    args = parser.parse_args()

    tasks_filter = [t.strip() for t in args.tasks.split(",") if t.strip()] or None
    samples = load_samples(args.split, tasks_filter, args.limit)
    print(f"Model: {llm.MODEL}")
    print(f"Loaded {len(samples)} samples (split={args.split}, tasks={tasks_filter})")

    if not args.output:
        model_tag = llm.MODEL.replace("/", "_")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = os.path.join(OUTPUT_DIR, f"baseline_{model_tag}_{ts}.jsonl")

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
    with open(args.output, "a") as fout:
        for i, sample in enumerate(remaining):
            result = solve_baseline(sample, max_tokens=args.max_tokens)
            results.append(result)
            fout.write(json.dumps(result, ensure_ascii=False) + "\n")
            fout.flush()
            ok = "✓" if result["correct"] else "✗"
            print(f"[{i+1}/{len(remaining)}] {ok} {result['task']}[{result['id']}] "
                  f"pred={result['pred']} elapsed={result.get('elapsed_s', 0):.1f}s")

    elapsed = time.time() - t0
    correct = sum(1 for r in results if r["correct"])
    total = len(results)
    print(f"\n{'='*50}")
    print(f"Model: {llm.MODEL}")
    print(f"Results: {correct}/{total} = {correct/total*100:.1f}%")
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
