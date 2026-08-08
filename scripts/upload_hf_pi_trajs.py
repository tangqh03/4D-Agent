#!/usr/bin/env python
"""Package pi Stage-1/Stage-2 trajectories and upload to HF dataset.

Follows GenDoP's upload pattern (HfApi + token file, via HF_ENDPOINT mirror).

Sessions are pi session JSONLs (~/.pi/agent/sessions/):
  --tmp-pi_eval_*  -> Stage 1 (frames attached, single turn)
  --tmp-pi_ws_*    -> Stage 2 (native tools, multi-turn, embedded viewed frames)

Each tar ships with manifest.json mapping sample id -> session file,
matched by question text + answer fingerprint (same logic as case viewer).

Usage:
  HF_ENDPOINT=https://hf-mirror.com /home/admin/.conda/envs/star/bin/python \
      scripts/upload_hf_pi_trajs.py [--skip-upload]
"""
from __future__ import annotations

import argparse
import base64
import glob
import hashlib
import json
import os
import tarfile

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SESS_ROOT = os.path.expanduser("~/.pi/agent/sessions")
EXPORT = os.path.join(PROJ, "outputs", "hf_export")
TOKEN_FILE = "/mnt/xlab-nas-wm/gaozhe.gz/hf_datasets/hf_tokens.txt"
REPO = "MihailSlutsky/vistr-pi-trajectories"

STAGES = {
    "stage1": {
        "glob": os.path.join(SESS_ROOT, "--tmp-pi_eval_*", "*.jsonl"),
        "pred": os.path.join(PROJ, "outputs", "predictions",
                             "pi_qwen3-vl-plus_dev_20260806.jsonl"),
    },
    "stage2": {
        "glob": os.path.join(SESS_ROOT, "--tmp-pi_ws_*", "*.jsonl"),
        "pred": os.path.join(PROJ, "outputs", "predictions",
                             "pi_agentic_qwen3-vl-plus_dev_20260806.jsonl"),
    },
}

README = """---
license: cc-by-4.0
tags:
  - video-question-answering
  - agent-trajectories
  - spatial-temporal-reasoning
---

# ViSTR pi Harness Trajectories (qwen3-vl-plus)

Full agent trajectories from two evaluation setups on the ViSTR-Bench public
dev split (403 binary video-QA samples, 15 subtasks), using
[pi](https://github.com/earendil-works/pi) v0.84.0 as harness and
qwen3-vl-plus as the VLM.

| Stage | Setup | Accuracy | File |
|-------|-------|----------|------|
| 1 | 8 uniformly-sampled frames attached, single-turn QA, no tools | 54.6% | `stage1_trajectories.tar.gz` |
| 2 | workspace + source video, native tools (bash/read), agent extracts & inspects frames itself (avg 14.7 turns) | 53.8% | `stage2_trajectories.tar.gz` |

Union oracle of both stages: **71.7%** — the two modes are strongly complementary.

## Format

Each tar contains pi session JSONL files (one per sample; pi session format v3:
`session` header + `message` events; Stage-2 tool results embed the frames the
agent viewed as base64 JPEG) plus `manifest.json`:

```json
{"<sample_id>": {"session": "relative/path.jsonl", "task": "...", "gt": "...",
                 "pred": "...", "correct": true}}
```

Predictions per stage: `predictions_stage1.jsonl`, `predictions_stage2.jsonl`.

Sessions were matched to samples by question text + final-answer fingerprint;
a handful of unmatched sessions (smoke tests, retries) are excluded.
"""


def extract_question_and_final(path):
    question, final = None, ""
    first_img_md5 = None
    for line in open(path):
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("type") != "message":
            continue
        m = e["message"]
        c = m.get("content")
        if isinstance(c, str):
            c = [{"type": "text", "text": c}]
        if not isinstance(c, list):
            continue
        for p in c:
            if p.get("type") == "image" and first_img_md5 is None:
                first_img_md5 = hashlib.md5(p.get("data", "").encode()).hexdigest()
            if p.get("type") != "text":
                continue
            if m.get("role") == "user" and question is None and "【题目】" in p["text"]:
                question = p["text"].split("【题目】", 1)[1].split("\n", 1)[0].strip()
            elif m.get("role") == "assistant":
                final = p["text"]
    return question, final, first_img_md5


def stage1_frame_hashes(preds):
    """Sample id -> md5 of first attached frame (recomputed deterministically)."""
    import sys
    sys.path.insert(0, PROJ)
    from agent.eval_pi import _extract_frames
    from agent.tools import BENCH_DIR
    import tempfile

    hashes = {}
    for r in preds:
        video = os.path.join(BENCH_DIR, r["video"])
        with tempfile.TemporaryDirectory() as tmp:
            frames = _extract_frames(video, tmp, n=8)
            if not frames:
                continue
            with open(frames[0], "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            hashes[hashlib.md5(b64.encode()).hexdigest()] = r
    return hashes


def build_stage(stage, cfg):
    preds = [json.loads(l) for l in open(cfg["pred"])]
    by_q = {}
    for r in preds:
        by_q.setdefault(r["question"].strip(), []).append(r)
    frame_map = stage1_frame_hashes(preds) if stage == "stage1" else {}

    manifest = {}
    matched_files = {}
    for sf in sorted(glob.glob(cfg["glob"]), key=os.path.getmtime):
        try:
            q, final, img_md5 = extract_question_and_final(sf)
        except Exception:
            continue
        if not q:
            continue
        row = None
        if stage == "stage1":
            row = frame_map.get(img_md5)
        else:
            for r in by_q.get(q, []):
                tail = (r.get("raw_answer") or "")[-200:]
                if tail and tail in final[-1000:]:
                    row = r
                    break
            if row is None and len(by_q.get(q, [])) == 1:
                row = by_q[q][0]
        if row is None:
            continue
        matched_files[row["id"]] = sf  # later (rerun) sessions win
        manifest[str(row["id"])] = {
            "session": os.path.relpath(sf, SESS_ROOT),
            "task": row["task"], "gt": row["gt"],
            "pred": row.get("pred"), "correct": row.get("correct"),
        }

    print(f"{stage}: matched {len(matched_files)}/{len(preds)}")
    tar_path = os.path.join(EXPORT, f"{stage}_trajectories.tar.gz")
    with tarfile.open(tar_path, "w:gz") as tar:
        mf = os.path.join(EXPORT, f"{stage}_manifest.json")
        with open(mf, "w") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=1)
        tar.add(mf, arcname="manifest.json")
        for sid, sf in sorted(matched_files.items()):
            tar.add(sf, arcname=os.path.relpath(sf, SESS_ROOT))
    print(f"  -> {tar_path} ({os.path.getsize(tar_path)/1e6:.0f} MB)")
    return tar_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-upload", action="store_true")
    args = parser.parse_args()

    os.makedirs(EXPORT, exist_ok=True)
    tars = {s: build_stage(s, cfg) for s, cfg in STAGES.items()}

    if args.skip_upload:
        return

    from huggingface_hub import HfApi
    tok = open(TOKEN_FILE).read().strip()
    api = HfApi(token=tok)
    api.create_repo(REPO, repo_type="dataset", exist_ok=True)
    api.upload_file(path_or_fileobj=README.encode(), path_in_repo="README.md",
                    repo_id=REPO, repo_type="dataset")
    print("README uploaded", flush=True)
    for stage, cfg in STAGES.items():
        api.upload_file(path_or_fileobj=cfg["pred"],
                        path_in_repo=f"predictions_{stage}.jsonl",
                        repo_id=REPO, repo_type="dataset")
        print(f"predictions_{stage}.jsonl uploaded", flush=True)
    for stage, tar_path in tars.items():
        print(f"uploading {tar_path} ...", flush=True)
        api.upload_file(path_or_fileobj=tar_path,
                        path_in_repo=os.path.basename(tar_path),
                        repo_id=REPO, repo_type="dataset")
        print(f"{stage} done", flush=True)
    print("ALL DONE", flush=True)


if __name__ == "__main__":
    main()
