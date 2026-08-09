#!/usr/bin/env python
"""Build pi case viewer data bundle from the downloaded HF trajectory dataset.

Sibling of build_case_viewer.py for the HF-exported qwen3-vl-plus runs
(outputs/hf_export/). The uploaded stage2 predictions carry no tool_trace
(toolCall-id matching impossible), so this uses the tar's manifest.json
(sample_id -> session relpath) for exact matching — exact by construction.

Reuses build_case_viewer.py helpers (parse_session / shrink_image / save_traj)
and writes the same web/case_viewer/data/ schema the pi_case_viewer frontend
expects. S1/S2 only (the HF dataset has no S2.1-S2.4b stages).

Usage:
  /opt/conda/envs/spatialagent/bin/python scripts/build_case_viewer_hf.py
"""
from __future__ import annotations

import json
import os
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJ, "scripts"))
import build_case_viewer as bcv  # noqa: E402

EXPORT = os.path.join(PROJ, "outputs", "hf_export")
SESS_ROOT = os.path.join(EXPORT, "sessions")
S1_PATH = os.path.join(EXPORT, "predictions_stage1.jsonl")
S2_PATH = os.path.join(EXPORT, "predictions_stage2.jsonl")
MANIFEST = os.path.join(SESS_ROOT, "manifest.json")


def main():
    os.makedirs(os.path.join(bcv.OUT_DIR, "images"), exist_ok=True)
    manifest = json.load(open(MANIFEST))
    s1 = {r["id"]: r for r in bcv.load_jsonl(S1_PATH)}
    s2rows = bcv.load_jsonl(S2_PATH)

    # Exact sample_id -> trajectory via manifest (later/rerun sessions already
    # resolved by upload script; manifest wins by construction).
    matched = {}
    for sid, m in manifest.items():
        sf = os.path.join(SESS_ROOT, m["session"])
        if not os.path.exists(sf):
            continue
        try:
            _, _, events, images, _ = bcv.parse_session(sf)
        except Exception:
            continue
        if events:
            matched[int(sid)] = (events, images)
    print(f"manifest sessions: {len(manifest)}, parsed w/ events: {len(matched)}")

    # How many videos share each question template (for honest labeling).
    from collections import Counter
    tpl_videos = Counter(r["question"].strip() for r in s2rows)

    cases = []
    for r in sorted(s2rows, key=lambda x: (x["task"], x["id"])):
        cid = r["id"]
        if cid in matched:
            traj = bcv.save_traj(cid, matched, "images", str(cid))
            shared, n_sessions = False, 1
        else:
            traj, shared, n_sessions = [], False, 0
        s1r = s1.get(cid, {})
        cases.append({
            "id": cid, "task": r["task"], "dimension": r.get("dimension", ""),
            "question": r["question"], "options": r["options"],
            "gt": r["gt"], "video": r.get("video", ""),
            "s1": {"pred": s1r.get("pred"), "correct": s1r.get("correct"),
                   "raw": (s1r.get("raw_answer") or "")[:300]},
            "s2": {"pred": r.get("pred"), "correct": r.get("correct"),
                   "raw": (r.get("raw_answer") or "")[-500:],
                   "elapsed": round(r.get("elapsed_s", 0))},
            "traj": traj,
            "traj_shared": shared,
            "traj_videos": tpl_videos[r["question"].strip()],
            "traj_sessions": n_sessions,
            "s21": None, "s22": None, "s23": None, "s24": None,
            "traj21": [], "traj22": [], "traj23": [], "traj24": [],
        })

    with open(os.path.join(bcv.OUT_DIR, "cases.json"), "w") as f:
        json.dump(cases, f, ensure_ascii=False)
    n_traj = sum(1 for c in cases if c["traj"])
    size = sum(os.path.getsize(os.path.join(dp, fn))
               for dp, _, fns in os.walk(bcv.OUT_DIR) for fn in fns) / 1e6
    print(f"cases: {len(cases)} ({n_traj} with trajectory), bundle {size:.0f} MB")
    print(f"output: {bcv.OUT_DIR}")


if __name__ == "__main__":
    main()
