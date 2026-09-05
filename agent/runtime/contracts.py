"""Stable task and rollout records for the S2.8 runtime."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol, Sequence


@dataclass(frozen=True)
class AgentItem:
    id: str
    video_path: Path
    question: str
    options: tuple[str, ...]
    ground_truth: str | None = None
    task_type: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AttemptRecord:
    number: int
    status: str
    directory: str
    session_jsonl: list[str] = field(default_factory=list)
    session_html: list[str] = field(default_factory=list)
    conversation_path: str | None = None
    image_paths: list[str] = field(default_factory=list)
    artifact_errors: list[str] = field(default_factory=list)
    process_error: str | None = None


@dataclass
class RolloutRecord:
    id: str
    question: str
    task_description: str
    task_type: str
    predicted_answer: str | None
    hard: int | None
    soft: float | None
    response: str
    agent_ok: bool
    fail_reason: str
    n_turns: int
    usage: dict[str, Any]
    elapsed_s: float
    termination: dict[str, Any]
    policy_model: str
    observer_model: str
    final_attempt: int | None
    attempts: list[AttemptRecord]
    trajectory_dir: str
    session_jsonl: list[str]
    session_html: list[str]
    conversation_path: str | None
    image_paths: list[str]
    artifact_errors: list[str]
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.update(value.pop("extras"))
        return value


class DatasetAdapter(Protocol):
    def load(self, **selection: Any) -> Sequence[AgentItem]: ...


class AgentBackend(Protocol):
    def run_attempt(self, item: AgentItem, **kwargs: Any) -> dict[str, Any]: ...


class ToolBundle(Protocol):
    name: str
    tools: tuple[str, ...]
    extensions: tuple[Path, ...]
