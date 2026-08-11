#!/usr/bin/env python
"""Unit tests for the eval-side pi event-stream parsing in eval_pi_agentic.py.

Covers _parse_pi_json (multi-round tool traces), _repair_swallowed_tool_calls
(Bug-C fallback) and extract_answer. No LLM / pi binary involved.

Run:  /opt/conda/bin/python agent/tests/test_eval_pi_parse.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from agent.eval_pi_agentic import (
    _build_prompt,
    _parse_pi_json,
    _repair_swallowed_tool_calls,
    _select_answer,
    extract_answer,
)

FAILURES = []


def check(name, fn):
    try:
        fn()
        print(f"  ok: {name}")
    except AssertionError as e:
        FAILURES.append((name, e))
        print(f"  FAIL: {name}\n      {e}")
    except Exception as e:
        FAILURES.append((name, e))
        print(f"  ERROR: {name}\n      {type(e).__name__}: {e}")


# ── _repair_swallowed_tool_calls ──────────────────────────────────────
def t_repair_full_form_nested():
    text = ('thinking here <tool_call>{"name":"bash","arguments":{"cmd":"ffprobe video.mp4"}}'
            '</tool_call> more thinking')
    repaired, swallowed = _repair_swallowed_tool_calls(text)
    assert len(swallowed) == 1, swallowed
    assert '"cmd":"ffprobe video.mp4"' in swallowed[0]
    assert "<tool_call>" not in repaired and "</tool_call>" not in repaired, repaired


def t_repair_full_form_with_braces_in_args():
    # '}' inside the cmd string value must not truncate the capture
    text = '<tool_call>{"name":"bash","arguments":{"cmd":"echo \'}\'"}}</tool_call>'
    repaired, swallowed = _repair_swallowed_tool_calls(text)
    assert len(swallowed) == 1, swallowed
    assert repaired.strip() == "", repaired


def t_repair_remnant_flat():
    # Bug-C remnant: opening <tool_call> tag consumed, only JSON + close tag
    text = '{"name":"read","path":"frame.jpg"}</tool_call> tail'
    repaired, swallowed = _repair_swallowed_tool_calls(text)
    assert len(swallowed) == 1, swallowed
    assert "frame.jpg" in swallowed[0]
    assert "</tool_call>" not in repaired


def t_repair_remnant_nested():
    # [^{}]* only constrains `{`..`"name"` (no braces there); the greedy `.*`
    # captures the nested arguments object, so real bash calls ARE salvaged.
    text = '{"name":"bash","arguments":{"cmd":"ls"}}</tool_call> tail'
    repaired, swallowed = _repair_swallowed_tool_calls(text)
    assert len(swallowed) == 1, swallowed
    assert json.loads(swallowed[0])["arguments"]["cmd"] == "ls"


def t_repair_multiple_remnants_independently():
    text = ('{"name":"read","path":"a.jpg"}</tool_call> between '
            '{"name":"read_video_sequence","arguments":{"path":"v.mp4"}}</tool_call> tail')
    repaired, swallowed = _repair_swallowed_tool_calls(text)
    assert len(swallowed) == 2, swallowed
    assert json.loads(swallowed[0])["name"] == "read"
    assert json.loads(swallowed[1])["name"] == "read_video_sequence"
    assert repaired.strip() == "between  tail", repr(repaired)


def t_repair_ignores_bare_json_without_close_tag():
    text = '{"name":"bash","arguments":{"cmd":"ls"}}'  # no </tool_call>
    repaired, swallowed = _repair_swallowed_tool_calls(text)
    assert len(swallowed) == 0


# ── _parse_pi_json ────────────────────────────────────────────────────
def event_stream():
    return "\n".join([
        json.dumps({"type": "message_update",
                    "assistantMessageEvent": {"type": "thinking_delta", "delta": "pre-"}}),
        json.dumps({"type": "message_update",
                    "assistantMessageEvent": {"type": "text_delta", "delta": "warmup"}}),
        json.dumps({"type": "message_end", "message": {
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "round1 thought"},
                {"type": "toolCall", "id": "tc1", "name": "index_video",
                 "arguments": {"path": "video.mp4"}},
            ]},
            "usage": {"total_tokens": 100}}),
        json.dumps({"type": "tool_execution_end", "toolCallId": "tc1",
                    "toolName": "index_video", "result": {
                        "content": [{"type": "text", "text": "timeline"}],
                        "isError": False}}),
        json.dumps({"type": "message_end", "message": {
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "round2 thought"},
                {"type": "text", "text": "FINAL: Yes"},
            ]},
            "usage": {"total_tokens": 150}}),
    ])


def t_parse_basic_trace():
    reasoning, final_text, usage, n_calls, calls, results, termination = _parse_pi_json(event_stream())
    assert reasoning == "round1 thought" + "round2 thought", reasoning
    assert final_text == "FINAL: Yes", final_text
    assert usage == {"total_tokens": 150}, usage  # last message_end usage
    assert n_calls == 1
    assert calls[0]["id"] == "tc1" and calls[0]["name"] == "index_video"
    assert results[0]["toolCallId"] == "tc1"
    assert results[0]["isError"] is False
    assert results[0]["content"] == [{"type": "text", "text": "timeline"}]
    assert termination["stop_reason"] == "unknown"


def t_parse_image_result_collapsed():
    stream = "\n".join([
        json.dumps({"type": "message_end", "message": {"role": "assistant", "content": [
            {"type": "toolCall", "id": "t2", "name": "read_video_sequence",
             "arguments": {"path": "video.mp4", "start_s": 0, "end_s": 1}}]}}),
        json.dumps({"type": "tool_execution_end", "toolCallId": "t2",
                    "toolName": "read_video_sequence", "result": {
                        "content": [{"type": "image", "data": "a" * 999}], "isError": False}}),
    ])
    _, _, _, n, calls, results, _ = _parse_pi_json(stream)
    assert n == 1
    assert results[0]["content"] == [{"type": "image", "data_bytes": 999}]


def t_parse_swallowed_call_is_salvaged_into_trace():
    # Remnant-form JSON swallowed into thinking should still be visible in
    # the persisted trace, even though the model did not provide a pi id.
    stream = "\n".join([
        json.dumps({"type": "message_end", "message": {"role": "assistant", "content": [
            {"type": "thinking", "thinking": '{"name":"read_video_sequence","arguments":{"path":"video.mp4","start_s":1,"end_s":2}}</tool_call> done'}]}}),
    ])
    _, final_text, _, n, calls, results, _ = _parse_pi_json(stream)
    assert n == 1, n  # counted
    assert len(calls) == 1, calls
    assert calls[0]["id"] == "salvaged-1"
    assert calls[0]["name"] == "read_video_sequence"
    assert calls[0]["arguments"]["start_s"] == 1
    assert results == []


def t_parse_tool_calls_only_count_assistant_blocks():
    stream = "\n".join([
        json.dumps({"type": "message_end", "message": {"role": "tool", "content": [
            {"type": "toolCall", "id": "wrong", "name": "read", "arguments": {"path": "x.jpg"}}]}}),
        json.dumps({"type": "message_end", "message": {"role": "assistant", "content": [
            {"type": "toolCall", "id": "right", "name": "read", "arguments": {"path": "x.jpg"}}]}}),
    ])
    _, _, _, n, calls, _, _ = _parse_pi_json(stream)
    assert n == 1, n
    assert [c["id"] for c in calls] == ["right"]


def t_parse_final_text_last_nonempty_block():
    stream = "\n".join([
        json.dumps({"type": "message_end", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "first analysis"}]}}),
        json.dumps({"type": "message_end", "message": {"role": "assistant", "content": [
            {"type": "text", "text": ""}]}}),
        json.dumps({"type": "message_end", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "FINAL: No"}]}}),
    ])
    _, final_text, _, _, _, _, _ = _parse_pi_json(stream)
    assert final_text == "FINAL: No"


def t_parse_preserves_details_and_provider_error():
    stream = "\n".join([
        json.dumps({"type": "message_end", "message": {
            "role": "assistant", "content": [{
                "type": "toolCall", "id": "s1", "name": "submit_answer",
                "arguments": {"answer": "Blue", "key_claim": "distance decreases"},
            }], "stopReason": "toolUse"}}),
        json.dumps({"type": "tool_execution_end", "toolCallId": "s1",
                    "toolName": "submit_answer", "result": {
                        "content": [{"type": "text", "text": "Answer accepted"}],
                        "details": {"accepted": True, "closure": "confirmed"},
                        "isError": False}}),
        json.dumps({"type": "message_end", "message": {
            "role": "assistant", "content": [], "stopReason": "error",
            "errorMessage": "400: maximum context length exceeded"}}),
    ])
    _, _, _, _, _, results, termination = _parse_pi_json(stream)
    assert results[0]["details"] == {"accepted": True, "closure": "confirmed"}
    assert termination == {
        "stop_reason": "error",
        "provider_error_count": 1,
        "last_error": "400: maximum context length exceeded",
    }


# ── extract_answer ────────────────────────────────────────────────────
def t_extract_final_line_priority():
    options = ["Yes", "No"]
    assert extract_answer("FINAL: No", "blah", options) == "No"
    assert extract_answer("分析完 F I N A L: Yes", "blah", options) == "Yes"
    assert extract_answer("FINAL: No", "thinking Yes", options) == "No"  # FINAL wins
    assert extract_answer("final：No", "x", options) == "No"


def t_extract_overlapping_options_prefers_exact_long_option():
    options = ["Clockwise", "Counterclockwise"]
    assert extract_answer("FINAL: Counterclockwise", "", options) == "Counterclockwise"
    assert extract_answer("The motion is Counterclockwise.", "", options) == "Counterclockwise"


def t_extract_option_in_final_text():
    assert extract_answer("我觉得答案是 Yes，因为……", "", ["Yes", "No"]) == "Yes"


def t_extract_reasoning_fallback():
    assert extract_answer("", "思考了很久，答案是 No", ["Yes", "No"]) == "No"


def t_extract_none_when_absent():
    assert extract_answer("不知道", "没有结论", ["Yes", "No"]) is None


def t_select_s26_final_overrides_accepted_submit():
    calls = [{"id": "s1", "name": "submit_answer", "arguments": {"answer": "Blue"}}]
    results = [{"toolCallId": "s1", "name": "submit_answer", "isError": False,
                "details": {"accepted": True}}]
    assert _select_answer("FINAL: Green", "", ["Green", "Blue"], calls, results,
                          has_submit=True) == ("Green", "final")


def t_select_s26_uses_last_accepted_submit_not_reasoning():
    # Historical #332 shape: Blue was committed, but a later relational phrase
    # mentioned green and the old reasoning fallback selected Green.
    calls = [
        {"id": "s1", "name": "submit_answer", "arguments": {"answer": "Blue"}},
        {"id": "s2", "name": "submit_answer", "arguments": {"answer": "Blue"}},
    ]
    results = [
        {"toolCallId": "s1", "name": "submit_answer", "isError": False,
         "details": {"accepted": False}},
        {"toolCallId": "s2", "name": "submit_answer", "isError": False,
         "details": {"accepted": True}},
    ]
    reasoning = 'submit answer "Blue" for the decreasing distance between blue and green'
    assert _select_answer("", reasoning, ["Green", "Blue"], calls, results,
                          has_submit=True) == ("Blue", "accepted_submit")


def t_select_s26_rejected_only_is_no_answer():
    calls = [{"id": "s1", "name": "submit_answer", "arguments": {"answer": "No"}}]
    results = [{"toolCallId": "s1", "name": "submit_answer", "isError": False,
                "details": {"accepted": False}}]
    assert _select_answer("", "I think No", ["Yes", "No"], calls, results,
                          has_submit=True) == (None, "none")


def t_select_non_s26_keeps_reasoning_fallback():
    assert _select_answer("", "I think No", ["Yes", "No"], [], [],
                          has_submit=False) == ("No", "reasoning_fallback")


def t_build_prompt_s28_has_no_submit_tool():
    prompt = _build_prompt("Question?", ["Yes", "No"],
                           "agent/pi_ext/vistr_video_tools.ts")
    assert "semantic_crop 工具" in prompt
    assert "submit_answer" not in prompt
    assert "FINAL: <选项原文之一>" in prompt


def t_build_prompt_closure_keeps_submit_protocol():
    prompt = _build_prompt(
        "Question?", ["Yes", "No"],
        "agent/pi_ext/vistr_video_tools.ts,agent/pi_ext/evidence_closure.ts")
    assert "调用 submit_answer 工具提交你的答案" in prompt
    assert "submit_answer 会检查" in prompt
    assert "FINAL: <选项原文之一>" in prompt


if __name__ == "__main__":
    print("test_eval_pi_parse.py")
    for f in [t_repair_full_form_nested, t_repair_full_form_with_braces_in_args,
              t_repair_remnant_flat, t_repair_remnant_nested,
              t_repair_multiple_remnants_independently,
              t_repair_ignores_bare_json_without_close_tag,
              t_parse_basic_trace, t_parse_image_result_collapsed,
              t_parse_swallowed_call_is_salvaged_into_trace,
              t_parse_tool_calls_only_count_assistant_blocks,
              t_parse_final_text_last_nonempty_block,
              t_parse_preserves_details_and_provider_error,
              t_extract_final_line_priority,
              t_extract_overlapping_options_prefers_exact_long_option,
              t_extract_option_in_final_text,
              t_extract_reasoning_fallback, t_extract_none_when_absent,
              t_select_s26_final_overrides_accepted_submit,
              t_select_s26_uses_last_accepted_submit_not_reasoning,
              t_select_s26_rejected_only_is_no_answer,
              t_select_non_s26_keeps_reasoning_fallback,
              t_build_prompt_s28_has_no_submit_tool,
              t_build_prompt_closure_keeps_submit_protocol]:
        check(f.__name__, f)
    if FAILURES:
        print(f"\n{len(FAILURES)} failures")
        sys.exit(1)
    print("\nall passed")
