#!/usr/bin/env python
"""Build data bundle for the pi case viewer (web/case_viewer/).

Joins Stage-1/Stage-2 prediction JSONLs with pi session trajectories
(matched by question text + final-answer fingerprint), extracts the frames
the agent viewed (downscaled), and writes web/case_viewer/data/.

Usage:
  /opt/conda/bin/python scripts/build_case_viewer.py
  cd <project root> && python3 -m http.server 8765
  open http://<host>:8765/web/case_viewer/
"""
from __future__ import annotations

import base64
import glob
import io
import json
import os

import cv2
import numpy as np

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S1_PATH = os.path.join(PROJ, "outputs", "predictions",
                       "pi_qwen3-vl-plus_dev_20260806.jsonl")
S2_PATH = os.path.join(PROJ, "outputs", "predictions",
                       "pi_agentic_qwen3-vl-plus_dev_20260806.jsonl")
S21_PATH = os.path.join(PROJ, "outputs", "predictions",
                        "pi_agentic_ext_qwen_pt6_20260807.jsonl")
S22_PATH = os.path.join(PROJ, "outputs", "predictions",
                        "pi_agentic_ext2_qwen_pt6_20260807.jsonl")
S23_PATH = os.path.join(PROJ, "outputs", "predictions",
                        "pi_agentic_ext3_qwen_pt6_20260807.jsonl")
S24_PATH = os.path.join(PROJ, "outputs", "predictions",
                        "pi_agentic_ext4b_qwen_pt6_20260807.jsonl")
SESS_GLOB = os.path.expanduser("~/.pi/agent/sessions/--tmp-pi_ws_*/*.jsonl")
OUT_DIR = os.path.join(PROJ, "web", "case_viewer", "data")
IMG_W = 640
JPEG_Q = 70
MAX_TEXT = 1500


def load_jsonl(path):
    rows = []
    with open(path) as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return rows


def shrink_image(b64data):
    buf = np.frombuffer(base64.b64decode(b64data), np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if img is None:
        return None
    h, w = img.shape[:2]
    if w > IMG_W:
        img = cv2.resize(img, (IMG_W, int(h * IMG_W / w)))
    ok, enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, JPEG_Q])
    return enc.tobytes() if ok else None


def parse_session(path):
    """Return (question, final_text, events). Events reference images by index."""
    question = None
    final_text = ""
    events = []
    images = []
    for line in open(path):
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("type") != "message":
            continue
        m = e["message"]
        role = m.get("role")
        c = m.get("content")
        if isinstance(c, str):
            c = [{"type": "text", "text": c}]
        if not isinstance(c, list):
            continue
        for p in c:
            pt = p.get("type")
            if pt == "text":
                txt = p.get("text", "")
                if role == "user" and question is None and "【题目】" in txt:
                    question = txt.split("【题目】", 1)[1].split("\n", 1)[0].strip()
                if role == "assistant":
                    final_text = txt
                    events.append({"t": "text", "text": txt[:MAX_TEXT]})
                elif role == "toolResult":
                    events.append({"t": "result", "text": txt[:600]})
            elif pt == "toolCall" and role == "assistant":
                events.append({"t": "tool", "name": p.get("name", ""),
                               "args": json.dumps(p.get("arguments", {}),
                                                  ensure_ascii=False)[:500]})
            elif pt == "image":
                images.append(p.get("data", ""))
                events.append({"t": "img", "idx": len(images) - 1})
    return question, final_text, events, images


def match_sessions(pred_rows, sess_files):
    by_question = {}
    for r in pred_rows:
        by_question.setdefault(r["question"].strip(), []).append(r)
    matched = {}
    for sf in sess_files:
        try:
            question, final_text, events, images = parse_session(sf)
        except Exception:
            continue
        if not question or not events:
            continue
        row = None
        for r in by_question.get(question, []):
            tail = (r.get("raw_answer") or "")[-200:]
            if tail and tail in final_text[-1000:]:
                row = r
                break
        if row is None and len(by_question.get(question, [])) == 1:
            row = by_question[question][0]
        if row is None:
            continue
        # later sessions win (reruns overwrite smoke attempts)
        matched[row["id"]] = (events, images)
    return matched


def save_traj(cid, matched, subdir):
    if cid not in matched:
        return []
    events, images = matched[cid]
    img_dir = os.path.join(OUT_DIR, subdir, str(cid))
    saved = {}
    traj = []
    for ev in events:
        ev = dict(ev)
        if ev["t"] == "img":
            idx = ev.pop("idx")
            if idx not in saved:
                data = shrink_image(images[idx])
                if data is None:
                    continue
                os.makedirs(img_dir, exist_ok=True)
                fn = f"{idx:02d}.jpg"
                with open(os.path.join(img_dir, fn), "wb") as f:
                    f.write(data)
                saved[idx] = f"{subdir}/{cid}/{fn}"
            ev["src"] = saved[idx]
        traj.append(ev)
    return traj


def main():
    os.makedirs(os.path.join(OUT_DIR, "images"), exist_ok=True)
    s1 = {r["id"]: r for r in load_jsonl(S1_PATH)}
    s2rows = load_jsonl(S2_PATH)
    s21 = {}
    if os.path.exists(S21_PATH):
        s21 = {r["id"]: r for r in load_jsonl(S21_PATH)}
    s22 = {}
    if os.path.exists(S22_PATH):
        s22 = {r["id"]: r for r in load_jsonl(S22_PATH)}
    s23 = {}
    if os.path.exists(S23_PATH):
        s23 = {r["id"]: r for r in load_jsonl(S23_PATH)}
    s24 = {}
    if os.path.exists(S24_PATH):
        s24 = {r["id"]: r for r in load_jsonl(S24_PATH)}

    sess_files = sorted(glob.glob(SESS_GLOB), key=os.path.getmtime)
    print(f"sessions: {len(sess_files)}")
    matched = match_sessions(s2rows, sess_files)
    print(f"S2 matched trajectories: {len(matched)}/{len(s2rows)}")
    matched21 = match_sessions(list(s21.values()), sess_files) if s21 else {}
    print(f"S2.1 matched trajectories: {len(matched21)}/{len(s21)}")
    matched22 = match_sessions(list(s22.values()), sess_files) if s22 else {}
    print(f"S2.2 matched trajectories: {len(matched22)}/{len(s22)}")
    matched23 = match_sessions(list(s23.values()), sess_files) if s23 else {}
    print(f"S2.3 matched trajectories: {len(matched23)}/{len(s23)}")
    matched24 = match_sessions(list(s24.values()), sess_files) if s24 else {}
    print(f"S2.4b matched trajectories: {len(matched24)}/{len(s24)}")

    cases = []
    for r in sorted(s2rows, key=lambda x: (x["task"], x["id"])):
        cid = r["id"]
        traj = save_traj(cid, matched, "images")
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
            "s21": ({"pred": s21[cid].get("pred"), "correct": s21[cid].get("correct"),
                     "raw": (s21[cid].get("raw_answer") or "")[-500:],
                     "elapsed": round(s21[cid].get("elapsed_s", 0))}
                    if cid in s21 else None),
            "traj21": save_traj(cid, matched21, "images21"),
            "s22": ({"pred": s22[cid].get("pred"), "correct": s22[cid].get("correct"),
                     "elapsed": round(s22[cid].get("elapsed_s", 0))}
                    if cid in s22 else None),
            "traj22": save_traj(cid, matched22, "images22"),
            "s23": ({"pred": s23[cid].get("pred"), "correct": s23[cid].get("correct"),
                     "elapsed": round(s23[cid].get("elapsed_s", 0))}
                    if cid in s23 else None),
            "traj23": save_traj(cid, matched23, "images23"),
            "s24": ({"pred": s24[cid].get("pred"), "correct": s24[cid].get("correct"),
                     "elapsed": round(s24[cid].get("elapsed_s", 0))}
                    if cid in s24 else None),
            "traj24": save_traj(cid, matched24, "images24"),
        })

    with open(os.path.join(OUT_DIR, "cases.json"), "w") as f:
        json.dump(cases, f, ensure_ascii=False)
    n_traj = sum(1 for c in cases if c["traj"])
    size = sum(os.path.getsize(os.path.join(dp, fn))
               for dp, _, fns in os.walk(OUT_DIR) for fn in fns) / 1e6
    print(f"cases: {len(cases)} ({n_traj} with trajectory), bundle {size:.0f} MB")
    print(f"output: {OUT_DIR}")


if __name__ == "__main__":
    main()
