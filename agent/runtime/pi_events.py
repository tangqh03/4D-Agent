"""Parse Pi JSON event streams without depending on the benchmark adapter."""

from __future__ import annotations

import json
import re
from typing import Any


TOOL_CALL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)
SWALLOWED_TC_START_RE = re.compile(r'\{\s*"name"\s*:\s*"[^"]+"', re.DOTALL)
TOOL_CALL_END = "</tool_call>"


def repair_swallowed_tool_calls(reasoning: str) -> tuple[str, list[str]]:
    swallowed = TOOL_CALL_RE.findall(reasoning)
    repaired = TOOL_CALL_RE.sub("", reasoning)
    spans: list[tuple[int, int]] = []
    search_from = 0
    decoder = json.JSONDecoder()
    while True:
        close = repaired.find(TOOL_CALL_END, search_from)
        if close < 0:
            break
        found = None
        for match in SWALLOWED_TC_START_RE.finditer(repaired, search_from, close):
            raw = repaired[match.start():close].strip()
            try:
                payload, consumed = decoder.raw_decode(raw)
            except json.JSONDecodeError:
                continue
            if (raw[consumed:].strip() or not isinstance(payload, dict)
                    or not isinstance(payload.get("name"), str)):
                continue
            found = (match.start(), close + len(TOOL_CALL_END), raw)
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


def parse_pi_json(stdout: str) -> dict[str, Any]:
    thinking_blocks: list[str] = []
    text_blocks: list[str] = []
    thinking_deltas: list[str] = []
    text_deltas: list[str] = []
    usage: dict[str, Any] = {}
    tool_calls: list[dict[str, Any]] = []
    tool_results: list[dict[str, Any]] = []
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
            if delta.get("type") == "thinking_delta":
                thinking_deltas.append(delta.get("delta", ""))
            elif delta.get("type") == "text_delta":
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
                    if message.get("errorMessage"):
                        last_provider_error = str(message["errorMessage"])[:1000]
                for block in blocks:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "thinking":
                        thinking_blocks.append(block.get("thinking", ""))
                    elif block.get("type") == "text":
                        text_blocks.append(block.get("text", ""))
                    elif block.get("type") == "toolCall":
                        tool_calls.append({
                            "id": block.get("id", ""),
                            "name": block.get("name", ""),
                            "arguments": block.get("arguments", {}),
                        })
            if event.get("usage"):
                usage = event["usage"]
        elif event_type == "tool_execution_end":
            result = event.get("result", {}) or {}
            content = []
            for block in result.get("content", []) or []:
                if isinstance(block, dict) and block.get("type") == "image":
                    content.append({"type": "image", "mimeType": block.get("mimeType"),
                                    "data_bytes": len(block.get("data", ""))})
                else:
                    content.append(block)
            tool_results.append({
                "toolCallId": event.get("toolCallId", ""),
                "name": event.get("toolName", ""),
                "isError": bool(result.get("isError", False)),
                "content": content,
                "details": result.get("details") if isinstance(result.get("details"), dict) else {},
            })

    reasoning = "".join(thinking_blocks) if thinking_blocks else "".join(thinking_deltas)
    reasoning, swallowed = repair_swallowed_tool_calls(reasoning)
    for raw in swallowed:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        arguments = payload.get("arguments")
        if not isinstance(arguments, dict):
            arguments = {k: v for k, v in payload.items() if k != "name"}
        tool_calls.append({"id": f"salvaged-{len(tool_calls) + 1}",
                           "name": payload["name"], "arguments": arguments})
    final_text = next((v for v in reversed(text_blocks) if v.strip()), "")
    if not final_text:
        final_text = "".join(text_deltas)
    executed_ids = {r["toolCallId"] for r in tool_results if r["toolCallId"]}
    return {
        "reasoning": reasoning.strip(),
        "final_text": final_text.strip(),
        "usage": usage,
        "tool_calls": tool_calls,
        "tool_results": tool_results,
        "tools_executed": sum(1 for c in tool_calls if c["id"] in executed_ids),
        "tool_errors": sum(1 for r in tool_results if r["isError"]),
        "termination": {"stop_reason": stop_reason,
                        "provider_error_count": provider_error_count,
                        "last_error": last_provider_error},
    }


def extract_answer(final_text: str, reasoning: str,
                   options: tuple[str, ...] | list[str]) -> str | None:
    def clean(candidate: str) -> str:
        return candidate.strip().strip("。.**`\"'，, \n\t")

    def exact_or_contained(candidate: str) -> str | None:
        candidate = clean(candidate)
        for option in options:
            if option.casefold() == candidate.casefold():
                return option
        matches = [o for o in options if o.casefold() in candidate.casefold()]
        return max(matches, key=len) if matches else None

    def last_mention(text: str) -> str | None:
        low = text.casefold()
        mentions: list[tuple[int, int, str]] = []
        for option in options:
            start = 0
            needle = option.casefold()
            while True:
                index = low.find(needle, start)
                if index < 0:
                    break
                mentions.append((index, index + len(needle), option))
                start = index + 1
        mentions = [m for m in mentions if not any(
            other[2] != m[2] and len(other[2]) > len(m[2])
            and other[0] <= m[0] and other[1] >= m[1] for other in mentions)]
        return max(mentions, key=lambda m: (m[0], len(m[2])))[2] if mentions else None

    tagged_answers = re.findall(
        r"<answer>\s*(.*?)\s*</answer>", final_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    for candidate in reversed(tagged_answers):
        answer = exact_or_contained(candidate)
        if answer:
            return answer
    return last_mention(final_text) or last_mention(reasoning)
