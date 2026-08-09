#!/usr/bin/env python
"""Build data bundle for the pi case viewer (web/case_viewer/).

Joins Stage-1/Stage-2 prediction JSONLs with pi session trajectories
(matched by question text + final-answer fingerprint), extracts the frames
the agent viewed (downscaled), and writes web/case_viewer/data/.

Usage:
  /opt/conda/bin/python scripts/build_case_viewer.py
  cd <project root> && python3 -m http.server 8765
  open http://<host>:8765/web/case_viewer/

Stage prediction paths are overridable via env vars (defaults = current
S2.6 pipeline; use these to build bundles for other runs without editing
the file):
  VISTR_BCV_S1   baseline JSONL
  VISTR_BCV_S2   S2/S2.6 agentic JSONL (default: s26 dev403)
  VISTR_BCV_S21..S24  ext-run JSONLs (empty to skip a stage)
"""
from __future__ import annotations

import base64
import glob
import hashlib
import io
import json
import os

import cv2
import numpy as np

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _env_path(key, default):
    """Stage path override (VISTR_BCV_S* env vars); empty string = skip."""
    v = os.environ.get(key)
    return v if v is not None else default


S1_PATH = _env_path("VISTR_BCV_S1", os.path.join(
    PROJ, "outputs", "predictions",
    "pi_qwen3-vl-plus_dev_20260806.jsonl"))
S2_PATH = _env_path("VISTR_BCV_S2", os.path.join(
    PROJ, "outputs", "predictions",
    "pi_agentic_qwen3-vl-plus_dev_20260806.jsonl"))
S21_PATH = _env_path("VISTR_BCV_S21", os.path.join(
    PROJ, "outputs", "predictions",
    "pi_agentic_ext_qwen_pt6_20260807.jsonl"))
S22_PATH = _env_path("VISTR_BCV_S22", os.path.join(
    PROJ, "outputs", "predictions",
    "pi_agentic_ext2_qwen_pt6_20260807.jsonl"))
S23_PATH = _env_path("VISTR_BCV_S23", os.path.join(
    PROJ, "outputs", "predictions",
    "pi_agentic_ext3_qwen_pt6_20260807.jsonl"))
S24_PATH = _env_path("VISTR_BCV_S24", os.path.join(
    PROJ, "outputs", "predictions",
    "pi_agentic_ext4b_qwen_pt6_20260807.jsonl"))
S26_PATH = _env_path("VISTR_BCV_S26", os.path.join(
    PROJ, "outputs", "predictions",
    "pi_s26_dev_20260808.jsonl"))
S27_PATH = _env_path("VISTR_BCV_S27", os.path.join(
    PROJ, "outputs", "predictions",
    "pi_s27_dev_20260809.jsonl"))
S24FULL_PATH = _env_path("VISTR_BCV_S24FULL", os.path.join(
    PROJ, "outputs", "predictions",
    "pi_s24b_dev_20260809.jsonl"))
# session 根目录(支持 HF 下载包的 sessions/ 目录;默认本机 pi session 库)。
SESS_ROOT = _env_path("VISTR_BCV_SESS", os.path.expanduser("~/.pi/agent/sessions"))
SESS_GLOB = os.path.join(SESS_ROOT, "--tmp-pi_ws_*", "*.jsonl")
# HF 包 manifest.json(路径时用其 id->session 映射做精确匹配,如 hf_export/sessions/manifest.json)。
MANIFEST_PATH = _env_path("VISTR_BCV_MANIFEST", "")
# 输出目录(多 viewer 实例并存时指向各自目录,如 web/case_viewer/data_pt6)。
OUT_DIR = _env_path("VISTR_BCV_OUT", os.path.join(PROJ, "web", "case_viewer", "data"))
IMG_W = 640
JPEG_Q = 70
MAX_TEXT = 1500
# 思考块(thinking part)不截断——全文进 cases.json。
# (历史:MAX_THINK=1000 词中硬切,viewer 误读为"思考中断",#9 思考 1198 字符被切成 1000;
# 用户明确:不要上限,调试必须能看完整思考。chars 字段保留原始长度作标注。)
MAX_THINK = None


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
    """Return (question, final_text, events, images, tool_call_ids).
    Events reference images by index."""
    question = None
    final_text = ""
    events = []
    images = []
    call_ids = []
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
            elif pt == "thinking":
                t = p.get("thinking") or ""
                events.append({"t": "think", "text": t if MAX_THINK is None else t[:MAX_THINK],
                               "chars": len(t)})
            elif pt == "toolCall" and role == "assistant":
                events.append({"t": "tool", "name": p.get("name", ""),
                               "args": json.dumps(p.get("arguments", {}),
                                                  ensure_ascii=False)[:500]})
                if p.get("id"):
                    call_ids.append(p["id"])
            elif pt == "image":
                images.append(p.get("data", ""))
                events.append({"t": "img", "idx": len(images) - 1})
    return question, final_text, events, images, call_ids


def match_sessions(pred_rows, sess_files):
    """Two-stage trajectory matching.

    Stage 1 (exact): match a session to a prediction row by toolCall ids.
    vLLM tool-call ids (chatcmpl-tool-*) are unique per call, and prediction
    rows persist the executed subset in tool_trace, so the session for a
    video is uniquely identifiable even though ViSTR question texts are
    templated (403 ids vs 74 unique texts) and sessions carry no video
    path (video is always copied to video.mp4, workspace deleted after run).

    Stage 2 (template fallback): rows with no tool trace (src=error runs
    where pi exited before any tool call) get the question template's
    trajectory; the caller flags those in traj_shared/traj_videos.
    """
    by_id = {r["id"]: r for r in pred_rows}
    tid2row = {}                       # toolCall id -> row ids
    for r in pred_rows:
        for t in r.get("tool_trace") or []:
            tid2row.setdefault(t["id"], set()).add(r["id"])
    templates = {r["question"].strip() for r in pred_rows}
    exact = {}     # row id -> (events, images)
    tpl = {}       # question -> (events, images); later sessions win
    counts = {}    # question -> matched session count
    for sf in sess_files:
        try:
            question, final_text, events, images, call_ids = parse_session(sf)
        except Exception:
            continue
        if not question or not events:
            continue
        counts[question] = counts.get(question, 0) + 1
        row_id = None
        for tid in call_ids:
            rows = tid2row.get(tid)
            if rows and len(rows) == 1:
                row_id = next(iter(rows))
                break
        if row_id is not None:
            exact[row_id] = (events, images)
        elif question in templates:
            tpl[question] = (events, images)
    return exact, tpl, counts


def match_manifest(manifest_path, sess_root):
    """Exact matching via an HF package manifest (id -> session path).

    Used when VISTR_BCV_MANIFEST points at e.g. hf_export/sessions/manifest.json:
    the package ships its own authoritative id->session mapping (403 ids,
    unique sessions), which the local toolCall-id stage cannot reconstruct
    because the uploaded predictions are stripped of tool_trace.
    """
    man = json.load(open(manifest_path))
    exact = {}     # row id -> (events, images)
    counts = {}    # question -> matched session count
    for str_id, info in man.items():
        try:
            rid = int(str_id)
        except ValueError:
            continue
        sf = os.path.join(sess_root, info["session"])
        if not os.path.exists(sf):
            continue
        try:
            question, final_text, events, images, call_ids = parse_session(sf)
        except Exception:
            continue
        if not question or not events:
            continue
        exact[rid] = (events, images)
        counts[question] = counts.get(question, 0) + 1
    return exact, counts


def save_traj(key, matched, subdir, dirname):
    """Dump a matched trajectory's viewed frames; `dirname` is the image
    sub-directory (row id for exact matches, tpl_<hash> for fallbacks)."""
    if key not in matched:
        return []
    events, images = matched[key]
    img_dir = os.path.join(OUT_DIR, subdir, dirname)
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
                saved[idx] = f"{subdir}/{dirname}/{fn}"
            ev["src"] = saved[idx]
        traj.append(ev)
    return traj


def main():
    os.makedirs(os.path.join(OUT_DIR, "images"), exist_ok=True)
    # S1/S2 同 S21-24:预测文件缺失时跳过(默认路径指向 8b/s26 本地输出,
    # 不在仓库内;其他环境用 VISTR_BCV_S* 覆盖指向自己的文件)。
    s1 = {}
    if os.path.exists(S1_PATH):
        s1 = {r["id"]: r for r in load_jsonl(S1_PATH)}
    s2rows = []
    if os.path.exists(S2_PATH):
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
    if MANIFEST_PATH and os.path.exists(MANIFEST_PATH):
        exact, counts = match_manifest(MANIFEST_PATH, SESS_ROOT)
        # Manifest 覆盖不到的 id 再用模板级兜底(不应发生,403 全量唯一映射)。
        missing = [r for r in s2rows if r["id"] not in exact]
        _, tpl, _ = match_sessions(missing, sess_files) if missing else ({}, {}, {})
        print(f"S2 exact (manifest): {len(exact)} rows, "
              f"fallback: {len(tpl)} templates, {sum(counts.values())} sessions")
    else:
        exact, tpl, counts = match_sessions(s2rows, sess_files)
        print(f"S2 exact (toolCall-id): {len(exact)} rows, "
              f"template fallback: {len(tpl)} templates, "
              f"{sum(counts.values())} sessions total")
    exact21, tpl21, _ = match_sessions(list(s21.values()), sess_files) if s21 else ({}, {}, {})
    print(f"S2.1 exact: {len(exact21)} rows, fallback: {len(tpl21)}")
    exact22, tpl22, _ = match_sessions(list(s22.values()), sess_files) if s22 else ({}, {}, {})
    print(f"S2.2 exact: {len(exact22)} rows, fallback: {len(tpl22)}")
    exact23, tpl23, _ = match_sessions(list(s23.values()), sess_files) if s23 else ({}, {}, {})
    print(f"S2.3 exact: {len(exact23)} rows, fallback: {len(tpl23)}")
    exact24, tpl24, _ = match_sessions(list(s24.values()), sess_files) if s24 else ({}, {}, {})
    print(f"S2.4b exact: {len(exact24)} rows, fallback: {len(tpl24)}")

    # How many videos share each question template (for honest labeling).
    from collections import Counter
    tpl_videos = Counter(r["question"].strip() for r in s2rows)

    s26 = {}
    if os.path.exists(S26_PATH):
        s26 = {r["id"]: r for r in load_jsonl(S26_PATH)}
    matched26 = match_sessions(list(s26.values()), sess_files) if s26 else {}
    print(f"S2.6 matched trajectories: {len(matched26)}/{len(s26)}")

    s27 = {}
    if os.path.exists(S27_PATH):
        s27 = {r["id"]: r for r in load_jsonl(S27_PATH)}
    matched27 = match_sessions(list(s27.values()), sess_files) if s27 else {}
    print(f"S2.7 matched trajectories: {len(matched27)}/{len(s27)}")

    s24full = {}
    if os.path.exists(S24FULL_PATH):
        s24full = {r["id"]: r for r in load_jsonl(S24FULL_PATH)}
    matched24full = match_sessions(list(s24full.values()), sess_files) if s24full else {}
    print(f"S2.4b-full matched trajectories: {len(matched24full)}/{len(s24full)}")

    cases = []
    for r in sorted(s2rows, key=lambda x: (x["task"], x["id"])):
        cid = r["id"]
        qkey = r["question"].strip()
        if cid in exact:
            traj = save_traj(cid, exact, "images", str(cid))
            shared, n_sessions = False, 0
        elif qkey in tpl:
            dirname = "tpl_" + hashlib.md5(qkey.encode()).hexdigest()[:10]
            traj = save_traj(qkey, tpl, "images", dirname)
            shared, n_sessions = True, counts.get(qkey, 0)
        else:
            traj = []
            shared, n_sessions = False, 0
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
            # Exact match (toolCall-id) => traj_shared False.  Template
            # fallback (only for rows without tool trace) => flagged so the
            # frontend labels the trajectory as template-level.
            "traj_shared": shared,
            "traj_videos": tpl_videos[qkey],
            "traj_sessions": n_sessions or counts.get(qkey, 0),
            "s21": ({"pred": s21[cid].get("pred"), "correct": s21[cid].get("correct"),
                     "raw": (s21[cid].get("raw_answer") or "")[-500:],
                     "elapsed": round(s21[cid].get("elapsed_s", 0))}
                    if cid in s21 else None),
            "traj21": (save_traj(cid, exact21, "images21", str(cid))
                       if cid in exact21 else
                       save_traj(qkey, tpl21, "images21",
                                 "tpl_" + hashlib.md5(qkey.encode()).hexdigest()[:10])),
            "s22": ({"pred": s22[cid].get("pred"), "correct": s22[cid].get("correct"),
                     "elapsed": round(s22[cid].get("elapsed_s", 0))}
                    if cid in s22 else None),
            "traj22": (save_traj(cid, exact22, "images22", str(cid))
                       if cid in exact22 else
                       save_traj(qkey, tpl22, "images22",
                                 "tpl_" + hashlib.md5(qkey.encode()).hexdigest()[:10])),
            "s23": ({"pred": s23[cid].get("pred"), "correct": s23[cid].get("correct"),
                     "elapsed": round(s23[cid].get("elapsed_s", 0))}
                    if cid in s23 else None),
            "traj23": (save_traj(cid, exact23, "images23", str(cid))
                       if cid in exact23 else
                       save_traj(qkey, tpl23, "images23",
                                 "tpl_" + hashlib.md5(qkey.encode()).hexdigest()[:10])),
            "s24": ({"pred": s24[cid].get("pred"), "correct": s24[cid].get("correct"),
                     "elapsed": round(s24[cid].get("elapsed_s", 0))}
                    if cid in s24 else None),
            "traj24": (save_traj(cid, exact24, "images24", str(cid))
                       if cid in exact24 else
                       save_traj(qkey, tpl24, "images24",
                                 "tpl_" + hashlib.md5(qkey.encode()).hexdigest()[:10])),
            "s26": ({"pred": s26[cid].get("pred"), "correct": s26[cid].get("correct"),
                     "elapsed": round(s26[cid].get("elapsed_s", 0))}
                    if cid in s26 else None),
            "traj26": save_traj(cid, matched26, "images26"),
            "s27": ({"pred": s27[cid].get("pred"), "correct": s27[cid].get("correct"),
                     "elapsed": round(s27[cid].get("elapsed_s", 0))}
                    if cid in s27 else None),
            "traj27": save_traj(cid, matched27, "images27"),
            "s24full": ({"pred": s24full[cid].get("pred"), "correct": s24full[cid].get("correct"),
                         "elapsed": round(s24full[cid].get("elapsed_s", 0))}
                        if cid in s24full else None),
            "traj24full": save_traj(cid, matched24full, "images24full"),
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
