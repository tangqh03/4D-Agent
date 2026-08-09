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
EXTENSION = os.environ.get("VISTR_PI_EXTENSION", "")

# Repo toolchain (see agent/tools/, eval_baseline.py): cv2 lives in the
# /opt/conda python; ffmpeg/ffprobe come from a conda env that has them.
# Both dirs are prepended to PATH so the pi agent's bash sees real tools.
CV2_PYTHON_DIR = "/opt/conda/bin"
FFMPEG_ENV_DIR = "/opt/conda/envs/spatialagent/bin"   # ffmpeg 8.1.2 + ffprobe + cv2 4.11


def agent_env():
    """PATH for the pi subprocess: repo cv2 python + a conda env with
    ffmpeg/ffprobe, keeping the original PATH as fallback."""
    env = os.environ.copy()
    paths = [p for p in (CV2_PYTHON_DIR, FFMPEG_ENV_DIR) if os.path.isdir(p)]
    if paths:
        env["PATH"] = ":".join(paths + [env.get("PATH", "")])
    return env


PROMPT = """你是视频时空推理专家。当前工作目录下有一个源视频 `video.mp4`（本目录可自由读写）。

可用手段：
- bash 工具：`ffmpeg`/`ffprobe` 已装；`/opt/conda/bin/python` 带 cv2/numpy，可抽帧、算光流、差分、裁剪放大等
- read 工具：可直接查看图片文件（jpg/png），看抽出的帧{extra_tools}

任务：先用工具分析视频（建议先 ffprobe 看时长帧率，再抽关键帧查看；关键区域可裁剪放大），然后回答：

【题目】{question}
【选项】{options}

要求：分析完成后，调用 submit_answer 工具提交你的答案（提供选项原文和你答案依赖的最关键视觉事实）。{final_instruction}"""

FINAL_INSTRUCTION_WITH_SUBMIT = """\
submit_answer 会检查你的关键事实是否已被直接视觉观察确认。如果发现证据缺口，你有一次机会去重新观察关键时刻再提交。\
submit_answer 确认后，在新的一行写：FINAL: <选项原文之一>"""

FINAL_INSTRUCTION_NO_SUBMIT = """\
最后单独一行输出你的答案，格式：FINAL: <选项原文之一>"""

EXTRA_TOOLS_NOTE = """
- index_video 工具：获取视频的粗粒度带 caption 时间线（纯文本），用于发现值得看的时刻
- read_video_sequence 工具：一次查看一个连续时间片段（多帧按时序排列）
- read_multiframe 工具：一次联合查看若干已选定的证据时刻的帧
- read_crop 工具：用归一化 bbox（0-1000）放大查看某帧/某图的局部区域（原始分辨率）
- semantic_crop 工具：用英文文字描述目标（如 "the hand touching the tower"），由 grounding 后端定位并返回高清局部图+定位回执
- submit_answer 工具：提交最终答案（提供选项原文 + 最关键视觉事实），系统会检查证据闭合"""


TOOL_CALL_RE = re.compile(
    r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL
)
# vLLM qwen3 reasoning_parser may consume the opening ``<tool_call>`` tag
# as an implicit reasoning-end marker, leaving only JSON + ``</tool_call>``
# inside the thinking block.  The start matcher is paired with JSONDecoder
# below so nested arguments and multiple remnant calls are handled without a
# greedy regex crossing from one closing tag into the next.
SWALLOWED_TC_START_RE = re.compile(
    r"\{\s*\"name\"\s*:\s*\"[^\"]+\"",
    re.DOTALL,
)
TOOL_CALL_END = "</tool_call>"


def _repair_swallowed_tool_calls(reasoning):
    """vLLM qwen3 reasoning_parser may swallow ``<tool_call>{...}</tool_call>``
    into the thinking block when the model doesn't close ``</think>`` first
    (known Qwen3.5 behaviour, see vllm/reasoning/qwen3_reasoning_parser.py
     lines 35-38).  Salvage the JSON so we can still extract an answer."""
    # Full-form: <tool_call>JSON</tool_call>
    swallowed = TOOL_CALL_RE.findall(reasoning)
    repaired = TOOL_CALL_RE.sub("", reasoning)

    # Remnant-form: JSON}</tool_call> (opening tag consumed by parser).
    # Search one closing marker at a time.  A greedy regex can consume two
    # adjacent calls as one invalid blob, losing both from the trace.
    spans = []
    search_from = 0
    decoder = json.JSONDecoder()
    while True:
        close = repaired.find(TOOL_CALL_END, search_from)
        if close < 0:
            break
        found = None
        for m in SWALLOWED_TC_START_RE.finditer(repaired, search_from, close):
            raw = repaired[m.start():close].strip()
            try:
                payload, consumed = decoder.raw_decode(raw)
            except json.JSONDecodeError:
                continue
            if raw[consumed:].strip() or not isinstance(payload, dict) or not isinstance(payload.get("name"), str):
                continue
            found = (m.start(), close + len(TOOL_CALL_END), raw)
            break
        if found is None:
            search_from = close + len(TOOL_CALL_END)
            continue
        start, end, raw = found
        swallowed.append(raw)
        spans.append((start, end))
        search_from = end

    for start, end in reversed(spans):
        repaired = repaired[:start] + repaired[end:]
    return repaired, swallowed


def _parse_pi_json(stdout):
    """Extract full thinking trace, final text, usage, tool-call trace and
    tool results from pi's JSON event stream (multi-round agentic sessions
    included).

    Only assistant-role messages carry thinking/text/toolCall blocks; toolResult
    messages carry the tool output as plain text and must be skipped.
    pi emits tool_execution_* events alongside; tool_execution_end carries the
    final result (content + isError) of each executed call.
    """
    thinking_blocks = []
    text_blocks = []
    thinking_deltas = []
    text_deltas = []
    usage = {}
    n_tool_calls = 0
    tool_calls = []      # {id, name, arguments} from assistant toolCall blocks
    tool_results = []    # {toolCallId, name, isError, content, details} from tool_execution_end
    stop_reason = "unknown"
    provider_error_count = 0
    last_provider_error = None

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
            role = message.get("role") if isinstance(message, dict) else None
            blocks = message.get("content", []) if isinstance(message, dict) else []
            if role == "assistant":
                reason = message.get("stopReason")
                if isinstance(reason, str) and reason:
                    stop_reason = reason
                if reason == "error":
                    provider_error_count += 1
                    error_message = message.get("errorMessage")
                    if error_message:
                        last_provider_error = str(error_message)[:1000]
            for block in blocks:
                if isinstance(block, dict):
                    bt = block.get("type")
                    if role == "assistant":
                        if bt == "thinking":
                            thinking_blocks.append(block.get("thinking", ""))
                        elif bt == "text":
                            text_blocks.append(block.get("text", ""))
                        if bt == "toolCall":
                            n_tool_calls += 1
                            tool_calls.append({
                                "id": block.get("id", ""),
                                "name": block.get("name", ""),
                                "arguments": block.get("arguments", {}),
                            })
            if event.get("usage"):
                usage = event.get("usage")
        elif event_type == "tool_execution_end":
            result = event.get("result", {}) or {}
            content = []
            for c in result.get("content", []) or []:
                if isinstance(c, dict) and c.get("type") == "image":
                    # Keep the persisted trace lean: image payloads are
                    # multi-hundred-KB base64 blobs; record size instead.
                    data = c.get("data", "")
                    content.append({"type": "image", "data_bytes": len(data)})
                else:
                    content.append(c)
            tool_results.append({
                "toolCallId": event.get("toolCallId", ""),
                "name": event.get("toolName", ""),
                "isError": bool(result.get("isError", False)),
                "content": content,
                "details": result.get("details") if isinstance(result.get("details"), dict) else {},
            })

    # Full reasoning = all thinking blocks across every assistant round.
    reasoning = "".join(thinking_blocks) if thinking_blocks else "".join(thinking_deltas)
    # Repair: salvage tool_calls swallowed into thinking by vLLM reasoning_parser.
    reasoning, swallowed_tcs = _repair_swallowed_tool_calls(reasoning)
    for raw in swallowed_tcs:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict) or not isinstance(payload.get("name"), str):
            continue
        arguments = payload.get("arguments")
        if not isinstance(arguments, dict):
            arguments = {k: v for k, v in payload.items() if k != "name"}
        tool_calls.append({
            # The model's swallowed form has no pi tool-call id.  Preserve
            # it in the trace with an explicit synthetic id; it must not be
            # counted as executed unless a real matching result exists.
            "id": f"salvaged-{len(tool_calls) + 1}",
            "name": payload["name"],
            "arguments": arguments,
        })
        n_tool_calls += 1
    # Final answer = last non-empty assistant text block (fall back to deltas).
    final_text = ""
    for t in text_blocks:
        if t.strip():
            final_text = t
    if not final_text:
        final_text = "".join(text_deltas)
    termination = {
        "stop_reason": stop_reason,
        "provider_error_count": provider_error_count,
        "last_error": last_provider_error,
    }
    return (reasoning.strip(), final_text.strip(), usage, n_tool_calls,
            tool_calls, tool_results, termination)


def extract_answer(final_text, reasoning, options):
    """Extract the chosen option from the final text, then reasoning.

    Priority: FINAL:/答案:/answer: line → option mentioned in final text →
    last option mentioned anywhere in reasoning (sessions that ended mid-loop
    may only carry the answer inside their thinking)."""
    def _match(cand):
        cand = cand.strip().strip("。.**`\"'，, \n\t")
        if not cand:
            return None
        # Prefer an exact option before substring fallback.  This matters for
        # the public split's Clockwise/Counterclockwise pair.
        for o in options:
            if o.casefold() == cand.casefold():
                return o
        matches = [o for o in options if o.casefold() in cand.casefold()]
        if matches:
            return max(matches, key=len)
        return cand

    def _last_option_mention(text):
        low = text.casefold()
        mentions = []
        for o in options:
            needle = o.casefold()
            start = 0
            while True:
                i = low.find(needle, start)
                if i < 0:
                    break
                mentions.append((i, i + len(needle), o))
                start = i + 1
        # Do not let a shorter option win merely because it occurs inside a
        # longer option (e.g. Clockwise inside Counterclockwise).
        mentions = [m for m in mentions if not any(
            other[2] != m[2] and len(other[2]) > len(m[2]) and
            other[0] <= m[0] and other[1] >= m[1]
            for other in mentions
        )]
        if not mentions:
            return None
        return max(mentions, key=lambda m: (m[0], len(m[2])))[2]

    if final_text:
        for line in reversed(final_text.splitlines()):
            m = re.match(r"\s*(?:FINAL|答案|answer)[:：]\s*(.+)", line.strip(),
                         re.IGNORECASE)
            if m:
                r = _match(m.group(1))
                if r:
                    return r
        mentioned = _last_option_mention(final_text)
        if mentioned:
            return mentioned

    if reasoning:
        mentioned = _last_option_mention(reasoning)
        if mentioned:
            return mentioned
    return None


def _select_answer(final_text, reasoning, options, tool_calls, tool_results,
                   has_submit):
    """Select an answer without mistaking deliberation for an S2.6 commit.

    S2.6 requires an explicit final line or a successful submit_answer result.
    Other stages retain the historical final-text/reasoning fallback.
    """
    if has_submit:
        for line in reversed(final_text.splitlines()):
            if not re.match(r"\s*(?:FINAL|答案|answer)[:：]", line, re.IGNORECASE):
                continue
            pred = extract_answer(line, "", options)
            if pred in options:
                return pred, "final"

        calls_by_id = {call.get("id"): call for call in tool_calls if call.get("id")}
        committed = None
        for result in tool_results:
            if result.get("isError") or result.get("details", {}).get("accepted") is not True:
                continue
            call = calls_by_id.get(result.get("toolCallId"))
            if not call or call.get("name") != "submit_answer":
                continue
            answer = call.get("arguments", {}).get("answer")
            if not isinstance(answer, str):
                continue
            cleaned = answer.strip().strip("。.**`\"'，, \n\t")
            option = next((o for o in options if o.casefold() == cleaned.casefold()), None)
            if option is not None:
                committed = option
        if committed is not None:
            return committed, "accepted_submit"
        return None, "none"

    pred_from_final = extract_answer(final_text, "", options)
    if pred_from_final in options:
        return pred_from_final, "final"
    pred = extract_answer("", reasoning, options)
    if pred in options:
        return pred, "reasoning_fallback"
    return None, "none"


def solve_agentic(sample, timeout=600):
    video_path = os.path.join(BENCH_DIR, sample["video"])
    question = sample["direct_prompting"]
    options = sample["options"]
    t0 = time.time()

    with tempfile.TemporaryDirectory(prefix="pi_ws_") as ws:
        shutil.copy(video_path, os.path.join(ws, "video.mp4"))
        has_submit = EXTENSION and "evidence_closure" in EXTENSION
        prompt = PROMPT.format(
            question=question, options=" / ".join(options),
            extra_tools=EXTRA_TOOLS_NOTE if EXTENSION else "",
            final_instruction=FINAL_INSTRUCTION_WITH_SUBMIT if has_submit else FINAL_INSTRUCTION_NO_SUBMIT,
        )
        env = agent_env()   # PATH fix (ffmpeg/ffprobe/cv2 on PATH)
        if has_submit:
            env["VISTR_QUESTION"] = f"{question} Options: {' / '.join(options)}"
        cmd = [PI_BIN, "-p", "--mode", "json",
               "--provider", PROVIDER, "--model", MODEL]
        if EXTENSION:
            for ext in EXTENSION.split(","):
                ext = ext.strip()
                if ext:
                    cmd += ["-e", os.path.join(PROJ_DIR, ext) if not os.path.isabs(ext) else ext]
        cmd.append(prompt)
        try:
            last_err = None
            for attempt in range(3):
                proc = subprocess.run(cmd, capture_output=True, text=True,
                                      timeout=timeout, cwd=ws, env=env)
                out = proc.stdout.strip()
                if proc.returncode == 0:
                    break
                last_err = f"pi exit {proc.returncode}: {proc.stderr.strip()[:300]}"
                time.sleep(5 * (attempt + 1))
            else:
                raise RuntimeError(last_err)
            (reasoning, final_text, usage, n_tool_calls,
             tool_calls, tool_results, termination) = _parse_pi_json(proc.stdout)
            # Execution verification: only calls with a matching
            # tool_execution_end were actually run by pi.  A call with no
            # matching result was swallowed (pre-fix Bug C) or abandoned.
            executed_ids = {r["toolCallId"] for r in tool_results if r["toolCallId"]}
            tools_executed = sum(1 for c in tool_calls if c["id"] in executed_ids)
            tool_errors = sum(1 for r in tool_results if r["isError"])
            pred, answer_source = _select_answer(
                final_text, reasoning, options, tool_calls, tool_results, has_submit)
            closure_info = {}
            if has_submit:
                for line in (proc.stderr or "").split("\n"):
                    if "[evidence-closure] submit_answer" in line:
                        closure_info["submit_calls"] = closure_info.get("submit_calls", 0) + 1
                    elif "[evidence-closure] checker reply:" in line:
                        closure_info["checker_reply"] = line.split("checker reply:")[-1].strip()
            return {
                "id": sample["id"], "task": sample["task"],
                "gt": sample["answer"], "pred": pred,
                "correct": pred == sample["answer"],
                "answer_source": answer_source,
                "no_answer": pred is None,
                "termination": termination,
                "src": "pi_agentic_ext" if EXTENSION else "pi_agentic",
                "question": question, "options": options,
                "video": sample.get("video", ""),
                "dimension": sample.get("dimension", ""),
                "reasoning": reasoning,
                "final_answer": final_text,
                "raw_answer": final_text[:500],
                "usage": usage,
                "tool_calls": n_tool_calls,
                "tool_trace": tool_calls,
                "tool_results": tool_results,
                "tools_executed": tools_executed,
                "tool_errors": tool_errors,
                "elapsed_s": time.time() - t0,
                "model": MODEL,
                **({"closure": closure_info} if closure_info else {}),
            }
        except Exception as e:
            return {
                "id": sample["id"], "task": sample["task"],
                "gt": sample["answer"], "pred": None,
                "correct": False, "src": "error",
                "answer_source": "none", "no_answer": True,
                "termination": {
                    "stop_reason": "unknown", "provider_error_count": 0,
                    "last_error": None,
                },
                "question": question, "options": options,
                "reasoning": "", "final_answer": "",
                "raw_answer": "", "usage": {}, "tool_calls": 0,
                "tool_trace": [], "tool_results": [],
                "tools_executed": 0, "tool_errors": 0,
                "error": f"{type(e).__name__}: {str(e)[:300]}",
                "elapsed_s": time.time() - t0,
                "model": MODEL,
            }


def _self_check():
    """Fail fast if the toolchain/backend the agent depends on is broken."""
    import shutil
    problems = []
    if not os.path.isfile(PI_BIN):
        problems.append(f"pi binary missing: {PI_BIN}")
    for name, path in [("ffprobe", "ffprobe"), ("ffmpeg", "ffmpeg")]:
        if not shutil.which(name, path=agent_env()["PATH"]):
            problems.append(f"{name} not found on agent PATH")
    if not os.path.exists(os.path.join(CV2_PYTHON_DIR, "python")):
        problems.append(f"cv2 python missing: {CV2_PYTHON_DIR}/python")
    r = subprocess.run([CV2_PYTHON_DIR + "/python", "-c",
                        "import cv2; print(cv2.__version__)"],
                       capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        problems.append(f"cv2 import failed: {r.stderr.strip()[:200]}")
    if problems:
        raise SystemExit("\n".join(["Self-check failed:"] + problems))


def main():
    _self_check()
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", default="dev", choices=["dev", "eval", "all"])
    parser.add_argument("--tasks", type=str, default="")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--per-task", type=int, default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--output", type=str, default="")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--ids", type=str, default="",
                        help="Comma-separated sample IDs to run (overrides split/tasks/limit)")
    args = parser.parse_args()

    tasks_filter = [t.strip() for t in args.tasks.split(",") if t.strip()] or None
    samples = load_samples(args.split, tasks_filter, args.limit, per_task=args.per_task)
    if args.ids:
        target = set(int(x) for x in args.ids.split(",") if x.strip())
        samples = [s for s in samples if s["id"] in target]
        if len(samples) != len(target):
            missing = target - {s["id"] for s in samples}
            print(f"Warning: {len(missing)} IDs not found in split: {sorted(missing)}")
    print(f"Harness: pi agentic ({PI_BIN})")
    print(f"Model: {PROVIDER}/{MODEL}")
    print(f"Loaded {len(samples)} samples (split={args.split}, tasks={tasks_filter})")

    if not args.output:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = os.path.join(OUTPUT_DIR, f"pi_agentic_{MODEL}_{ts}.jsonl")
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
