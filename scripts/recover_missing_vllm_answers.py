#!/usr/bin/env python3
"""Recover truncated answers and merge them with the original ViSTR run.

The original runs are left untouched. Only records whose ``final_answer`` is
empty are sent again with a larger output budget; the recovered records are
then merged back into a new JSONL file.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_DIR)

from agent.eval_baseline import load_samples, solve_baseline
from agent.eval_pi import solve_pi


DEFAULT_BASELINE = os.path.join(
    PROJECT_DIR, "outputs", "predictions",
    "baseline_qwen3-vl-8b-thinking_vllm_dev_trace.jsonl",
)
DEFAULT_PI = os.path.join(
    PROJECT_DIR, "outputs", "predictions",
    "pi_qwen3-vl-8b-thinking_vllm_dev_trace.jsonl",
)


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def has_final_answer(row):
    return bool((row.get("final_answer") or "").strip())


def missing_samples(old_path, split, manifest_path):
    old_rows = read_jsonl(old_path)
    samples = {sample["id"]: sample for sample in load_samples(split)}
    missing_ids = [row["id"] for row in old_rows if not has_final_answer(row)]
    selected = [samples[i] for i in missing_ids if i in samples]
    manifest = {
        "source": old_path,
        "split": split,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "count": len(selected),
        "ids": [sample["id"] for sample in selected],
        "samples": selected,
    }
    os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return old_rows, selected


def recover(harness, samples, output_path, max_tokens, workers, timeout):
    recovered = read_jsonl(output_path) if os.path.exists(output_path) else []
    done_ids = {row["id"] for row in recovered if has_final_answer(row)}
    remaining = [sample for sample in samples if sample["id"] not in done_ids]
    print(f"{harness}: {len(samples)} missing originally, "
          f"{len(done_ids)} recovered already, {len(remaining)} to run", flush=True)

    lock = threading.Lock()
    count = [0]
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "a", encoding="utf-8") as fout:
        def run_one(sample):
            if harness == "baseline":
                result = solve_baseline(
                    sample, max_tokens=max_tokens, timeout=timeout)
            else:
                result = solve_pi(sample, timeout=timeout)
            result["recovery_budget"] = max_tokens
            result["recovery_harness"] = harness
            with lock:
                fout.write(json.dumps(result, ensure_ascii=False) + "\n")
                fout.flush()
                count[0] += 1
                status = "OK" if has_final_answer(result) else "NO_FINAL"
                print(f"{harness} [{count[0]}/{len(remaining)}] "
                      f"id={result['id']} {status} pred={result.get('pred')} "
                      f"elapsed={result.get('elapsed_s', 0):.1f}s", flush=True)
            return result

        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(run_one, remaining))
    return read_jsonl(output_path)


def merge(old_path, recovery_path, merged_path):
    old_rows = read_jsonl(old_path)
    recovered = {row["id"]: row for row in read_jsonl(recovery_path)}
    merged = []
    replaced = 0
    for old in old_rows:
        replacement = recovered.get(old["id"])
        if replacement is not None and has_final_answer(replacement):
            replacement = dict(replacement)
            replacement["merged_from_original"] = old_path
            merged.append(replacement)
            replaced += 1
        else:
            merged.append(old)
    write_jsonl(merged_path, merged)
    print(f"merged {os.path.basename(merged_path)}: {replaced} recovered records, "
          f"{len(merged)} total", flush=True)


def run_one_harness(harness, old_path, split, output_dir, max_tokens, workers, timeout):
    model_tag = "qwen3-vl-8b-thinking"
    stem = f"{harness}_{model_tag}_vllm_{split}"
    manifest_path = os.path.join(output_dir, f"missing_{stem}.json")
    recovery_path = os.path.join(output_dir, f"{stem}_recovery.jsonl")
    merged_path = os.path.join(
        PROJECT_DIR, "outputs", "predictions", f"{stem}_recovered_merged.jsonl"
    )
    old_rows, samples = missing_samples(old_path, split, manifest_path)
    print(f"{harness}: extracted {len(samples)} samples to {manifest_path}")
    recover(harness, samples, recovery_path, max_tokens, workers, timeout)
    merge(old_path, recovery_path, merged_path)
    return len(old_rows), len(samples), merged_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--harness", choices=["baseline", "pi", "both"], default="both")
    parser.add_argument("--split", default="dev", choices=["dev", "eval", "all"])
    parser.add_argument("--baseline", default=DEFAULT_BASELINE)
    parser.add_argument("--pi", default=DEFAULT_PI)
    parser.add_argument("--output-dir", default=os.path.join(PROJECT_DIR, "outputs", "recovery"))
    parser.add_argument("--max-tokens", type=int, default=16384)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args()

    started = time.time()
    jobs = []
    if args.harness in ("baseline", "both"):
        jobs.append(("baseline", args.baseline))
    if args.harness in ("pi", "both"):
        jobs.append(("pi", args.pi))

    for harness, old_path in jobs:
        run_one_harness(
            harness, old_path, args.split, args.output_dir,
            args.max_tokens, args.workers, args.timeout,
        )
    print(f"completed in {(time.time() - started) / 60:.1f} minutes")


if __name__ == "__main__":
    main()
