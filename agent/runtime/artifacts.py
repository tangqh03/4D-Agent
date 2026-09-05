"""Pi-native and SkillOpt-facing trajectory artifacts."""

from __future__ import annotations

import base64
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from .contracts import AgentItem, AttemptRecord


TEXT_LIMIT = 4000


def _safe(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    return value[:60] or "tool"


def _trim(text: str) -> str:
    if len(text) <= TEXT_LIMIT:
        return text
    return text[:TEXT_LIMIT] + f"\n...[truncated, {len(text)} chars total]"


def export_and_materialize(
    *, attempt_dir: Path, pi_binary: Path, env: dict[str, str],
    item: AgentItem, skill_content: str, user_prompt: str,
    predicted_answer: str | None, hard: int | None, soft: float | None,
    execution_error: str | None,
) -> AttemptRecord:
    sessions = sorted(attempt_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    record = AttemptRecord(number=int(attempt_dir.name.split("-")[-1]),
                           status="error" if execution_error else "completed",
                           directory=str(attempt_dir), process_error=execution_error)
    (attempt_dir / "skill.md").write_text(skill_content, encoding="utf-8")
    (attempt_dir / "target_user_prompt.txt").write_text(user_prompt, encoding="utf-8")
    for session in sessions:
        record.session_jsonl.append(str(session))
        html = session.with_suffix(".html")
        proc = subprocess.run([str(pi_binary), "--export", str(session), str(html)],
                              capture_output=True, text=True, env=env, timeout=120)
        if proc.returncode == 0 and html.is_file():
            record.session_html.append(str(html))
        else:
            record.artifact_errors.append(
                f"HTML export failed for {session.name}: {(proc.stderr or proc.stdout)[:300]}")
    if not sessions:
        record.artifact_errors.append("Pi produced no session JSONL")
        return record

    conversation, image_paths = _session_to_conversation(
        sessions[-1], attempt_dir, item, predicted_answer, hard, soft,
        execution_error)
    conversation_path = attempt_dir / "conversation.json"
    conversation_path.write_text(json.dumps(conversation, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    record.conversation_path = str(conversation_path)
    record.image_paths = [str(p) for p in image_paths]
    return record


def _session_to_conversation(
    session: Path, attempt_dir: Path, item: AgentItem,
    predicted_answer: str | None, hard: int | None, soft: float | None,
    execution_error: str | None,
) -> tuple[list[dict[str, Any]], list[Path]]:
    entries: list[dict[str, Any]] = []
    for line in session.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") == "message" and isinstance(entry.get("message"), dict):
            entries.append(entry["message"])

    conversation: list[dict[str, Any]] = [{
        "role": "user",
        "content": f"{item.question}\n\nOptions: {' / '.join(item.options)}"
                   f"\n\n[video] {item.video_path}",
    }]
    images_dir = attempt_dir / "images"
    images_dir.mkdir(exist_ok=True)
    image_paths: list[Path] = []
    call_events: dict[str, dict[str, Any]] = {}
    turn = 0
    for message in entries:
        role = message.get("role")
        content = message.get("content", []) or []
        if role == "assistant":
            visible = [str(b.get("text", "")) for b in content
                       if isinstance(b, dict) and b.get("type") == "text"
                       and str(b.get("text", "")).strip()]
            if visible:
                turn += 1
                conversation.append({"type": "message", "turn": turn,
                                     "content": _trim("\n".join(visible))})
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "toolCall":
                    continue
                turn += 1
                name = str(block.get("name", ""))
                arguments = block.get("arguments", {})
                event = {"type": "tool_call", "turn": turn,
                         "tool_call_id": block.get("id", ""),
                         "name": name, "arguments": arguments,
                         "cmd": f"{name}({json.dumps(arguments, ensure_ascii=False, sort_keys=True)})",
                         "observation": "", "obs": ""}
                conversation.append(event)
                call_events[str(block.get("id", ""))] = event
        elif role == "toolResult":
            call_id = str(message.get("toolCallId", ""))
            name = str(message.get("toolName", "tool"))
            event = call_events.get(call_id)
            if event is None:
                turn += 1
                event = {"type": "tool_call", "turn": turn,
                         "tool_call_id": call_id, "name": name,
                         "arguments": {}, "cmd": f"{name}({{}})",
                         "observation": "", "obs": ""}
                conversation.append(event)
                call_events[call_id] = event
            observations: list[str] = []
            image_index = 0
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    text = str(block.get("text", ""))
                    if text:
                        observations.append(_trim(text))
                elif block.get("type") == "image" and block.get("data"):
                    image_index += 1
                    mime = str(block.get("mimeType", "image/png"))
                    ext = {"image/jpeg": ".jpg", "image/png": ".png",
                           "image/webp": ".webp"}.get(mime, ".bin")
                    filename = (f"turn-{event['turn']:03d}_{_safe(name)}_"
                                f"{image_index:02d}{ext}")
                    path = images_dir / filename
                    try:
                        path.write_bytes(base64.b64decode(block["data"], validate=True))
                    except (ValueError, TypeError) as exc:
                        observations.append(f"[image decode error] {exc}")
                    else:
                        image_paths.append(path)
                        observations.append(f"[image] images/{filename}")
            if message.get("isError"):
                observations.append("[tool error]")
            observation = _trim("\n".join(observations))
            event["observation"] = observation
            event["obs"] = observation

    if execution_error:
        detail = f"[EXECUTION RESULT]\nError: {execution_error}"
    else:
        detail = ("[EVALUATION RESULT]\n"
                  f"Question: {item.question}\n"
                  f"Predicted answer: {predicted_answer!r}\n"
                  f"Gold answer: {item.ground_truth!r}\n"
                  f"Hard: {hard!r}\nSoft: {soft!r}")
    conversation.append({"role": "system", "content": detail})
    return conversation, image_paths
