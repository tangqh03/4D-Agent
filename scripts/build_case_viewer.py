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


def main():
    os.makedirs(os.path.join(OUT_DIR, "images"), exist_ok=True)
    s1 = {r["id"]: r for r in load_jsonl(S1_PATH)}
    s2rows = load_jsonl(S2_PATH)

    by_question = {}
    for r in s2rows:
        by_question.setdefault(r["question"].strip(), []).append(r)

    matched = {}
    sess_files = sorted(glob.glob(SESS_GLOB), key=os.path.getmtime)
    print(f"sessions: {len(sess_files)}")
    for sf in sess_files:
        try:
            question, final_text, events, images = parse_session(sf)
        except Exception:
            continue
        if not question or not events:
            continue
        cands = by_question.get(question, [])
        row = None
        for r in cands:
            tail = r.get("raw_answer", "")[-200:]
            if tail and tail in final_text[-1000:]:
                row = r
                break
        if row is None and len(cands) == 1:
            row = cands[0]
        if row is None:
            continue
        # later sessions win (reruns overwrite smoke attempts)
        matched[row["id"]] = (events, images)

    print(f"matched trajectories: {len(matched)}/{len(s2rows)}")

    cases = []
    for r in sorted(s2rows, key=lambda x: (x["task"], x["id"])):
        cid = r["id"]
        traj = []
        if cid in matched:
            events, images = matched[cid]
            img_dir = os.path.join(OUT_DIR, "images", str(cid))
            saved = {}
            for ev in events:
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
                        saved[idx] = f"images/{cid}/{fn}"
                    ev["src"] = saved[idx]
                traj.append(ev)
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
