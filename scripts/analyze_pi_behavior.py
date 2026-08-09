#!/usr/bin/env python
"""Compare agent behavior across pi agentic runs.

Runs:
  plus    — qwen3-vl-plus, native tools (bash/read/write/edit), sessions from
            the HF download (outputs/hf_export/, manifest-exact matching)
  8b_fix  — qwen3-vl-8b-thinking, native tools, local sessions
            (toolCall-id exact matching)
  8b_s26  — qwen3-vl-8b-thinking + vistr_video_tools + evidence_closure gate,
            local sessions (toolCall-id exact matching)

Axes: outcome, tool mix, tool calls / images viewed / thinking / text
verbosity (thinking parts are invisible in the case viewer — this script
surfaces them), assistant turns, elapsed.

Usage:
  /opt/conda/envs/spatialagent/bin/python scripts/analyze_pi_behavior.py
"""
from __future__ import annotations

import glob
import json
import os
import statistics
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJ, "scripts"))
import build_case_viewer as bcv  # noqa: E402

PREDS = {
    "plus": os.path.join(PROJ, "outputs", "hf_export", "predictions_stage2.jsonl"),
    "8b_fix": os.path.join(PROJ, "outputs", "predictions",
                           "pi_agentic_qwen3-vl-8b-thinking_vllm_dev_fix.jsonl"),
    "8b_s26": os.path.join(PROJ, "outputs", "predictions",
                           "pi_s26_qwen3-vl-8b-thinking_vllm_gpu01_dev403_20260808.jsonl"),
}
SESS_ROOTS = {
    "plus": os.path.join(PROJ, "outputs", "hf_export", "sessions"),
    "8b_fix": os.path.expanduser("~/.pi/agent/sessions"),
    "8b_s26": os.path.expanduser("~/.pi/agent/sessions"),
}
MANIFEST = os.path.join(PROJ, "outputs", "hf_export", "sessions", "manifest.json")


def session_stats(path):
    """(events, images, call_ids, thinking_chars, text_chars, n_assistant_msgs)."""
    events, images, call_ids = [], [], []
    thinking_chars = text_chars = n_assistant = 0
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
                if role == "assistant":
                    text_chars += len(txt)
                    events.append({"t": "text", "text": txt[:bcv.MAX_TEXT]})
                elif role == "toolResult":
                    events.append({"t": "result", "text": txt[:600]})
            elif pt == "thinking":
                thinking_chars += len(p.get("thinking") or "")
            elif pt == "toolCall" and role == "assistant":
                events.append({"t": "tool", "name": p.get("name", ""),
                               "args": json.dumps(p.get("arguments", {}),
                                                  ensure_ascii=False)[:500]})
                if p.get("id"):
                    call_ids.append(p["id"])
            elif pt == "image":
                images.append(p.get("data", ""))
                events.append({"t": "img", "idx": len(images) - 1})
        if role == "assistant":
            n_assistant += 1
    return events, images, call_ids, thinking_chars, text_chars, n_assistant


def match_by_toolcall_id(rows, sess_files):
    """row_id -> session path via unique toolCall ids (mirrors
    build_case_viewer.match_sessions but keeps the session path)."""
    tid2row = {}
    for r in rows.values():
        for t in r.get("tool_trace") or []:
            tid2row.setdefault(t["id"], set()).add(r["id"])
    templates = {r["question"].strip() for r in rows.values()}
    exact, tpl = {}, {}  # row_id -> path ; question -> path (later wins)
    for sf in sess_files:
        try:
            q, _final, events, _imgs, cids = bcv.parse_session(sf)
        except Exception:
            continue
        if not q or not events:
            continue
        row_id = None
        for tid in cids:
            rs = tid2row.get(tid)
            if rs and len(rs) == 1:
                row_id = next(iter(rs))
                break
        if row_id is not None:
            exact[row_id] = sf
        elif q in templates:
            tpl[q] = sf
    return exact, tpl


def collect(run):
    rows = {r["id"]: r for r in bcv.load_jsonl(PREDS[run])}
    sess_files = sorted(glob.glob(os.path.join(SESS_ROOTS[run],
                                               "--tmp-pi_ws_*", "*.jsonl")),
                        key=os.path.getmtime)
    per_case = {}
    if run == "plus":
        manifest = json.load(open(MANIFEST))
        for sid, m in manifest.items():
            sf = os.path.join(SESS_ROOTS["plus"], m["session"])
            if not os.path.exists(sf):
                continue
            ev, im, _cids, th, tx, na = session_stats(sf)
            if ev:
                per_case[int(sid)] = dict(events=ev, images=im, thinking=th,
                                          text=tx, turns=na, exact=True)
        return rows, per_case, {}
    exact, tpl = match_by_toolcall_id(rows, sess_files)
    for sid, sf in exact.items():
        ev, im, _cids, th, tx, na = session_stats(sf)
        per_case[sid] = dict(events=ev, images=im, thinking=th, text=tx,
                             turns=na, exact=True)
    return rows, per_case, tpl


def main():
    all_cases = {}
    for run in ("plus", "8b_fix", "8b_s26"):
        rows, per_case, tpl = collect(run)
        n = len(rows)
        acc = sum(1 for r in rows.values() if r.get("correct"))
        tools = {}
        tool_counts, img_counts, thinking, text, turns = [], [], [], [], []
        for sid, s in per_case.items():
            tc = sum(1 for e in s["events"] if e["t"] == "tool")
            tool_counts.append(tc)
            for e in s["events"]:
                if e["t"] == "tool":
                    tools[e["name"]] = tools.get(e["name"], 0) + 1
            img_counts.append(len(s["images"]))
            thinking.append(s["thinking"])
            text.append(s["text"])
            turns.append(s["turns"])
        print(f"== {run}: exact {len(per_case)}/{n} | acc {acc}/{n} = "
              f"{100*acc/n:.1f}%")
        print(f"   tools: {tools}")
        print(f"   tool calls/case mean={statistics.mean(tool_counts):.1f} "
              f"median={statistics.median(tool_counts)} "
              f"(sum={sum(tool_counts)})")
        print(f"   images viewed/case mean={statistics.mean(img_counts):.1f} "
              f"median={statistics.median(img_counts)}")
        print(f"   thinking chars/case mean={statistics.mean(thinking):.0f} "
              f"median={statistics.median(thinking):.0f}")
        print(f"   text chars/case mean={statistics.mean(text):.0f} "
              f"median={statistics.median(text):.0f}")
        print(f"   assistant turns/case mean={statistics.mean(turns):.1f}")
        el = [r.get("elapsed_s") or 0 for r in rows.values()]
        print(f"   elapsed_s mean={statistics.mean(el):.0f} "
              f"median={statistics.median(el):.0f}")
        all_cases[run] = rows
        print()

    # 每任务准确率对比
    tasks = sorted({r["task"] for r in all_cases["plus"].values()})
    print(f"{'task':<26}{'plus':>7}{'8b_fix':>8}{'8b_s26':>8}")
    for t in tasks:
        def acc(run):
            rs = [r for r in all_cases[run].values() if r["task"] == t]
            return f"{100*sum(r.get('correct') for r in rs)/len(rs):.0f}"
        print(f"{t:<26}{acc('plus'):>7}{acc('8b_fix'):>8}{acc('8b_s26'):>8}")

    # plus vs 8b_fix 分歧矩阵(同工具集,纯模型对比)
    ids = set(all_cases["plus"]) & set(all_cases["8b_fix"])
    m = {"both": 0, "plus_only": [], "fix_only": [], "neither": 0}
    for i in ids:
        pc, fc = all_cases["plus"][i].get("correct"), all_cases["8b_fix"][i].get("correct")
        if pc and fc:
            m["both"] += 1
        elif pc and not fc:
            m["plus_only"].append(i)
        elif fc and not pc:
            m["fix_only"].append(i)
        else:
            m["neither"] += 1
    print(f"\nplus vs 8b_fix ({len(ids)} ids): both✓ {m['both']} | plus✓only "
          f"{len(m['plus_only'])} | fix✓only {len(m['fix_only'])} | both✗ {m['neither']}")
    union = m["both"] + len(m["plus_only"]) + len(m["fix_only"])
    print(f"   union oracle: {union}/{len(ids)} = {100*union/len(ids):.1f}%")
    print(f"   plus-only ids: {m['plus_only'][:12]}")
    print(f"   fix-only ids: {m['fix_only'][:12]}")


if __name__ == "__main__":
    main()
