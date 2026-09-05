"""Closed registry of tool bundles supported by the current runtime."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RegisteredToolBundle:
    name: str
    tools: tuple[str, ...]
    extensions: tuple[Path, ...]


def get_tool_bundle(name: str) -> RegisteredToolBundle:
    if name != "s2_8_observation":
        raise ValueError(f"Unknown tool bundle: {name}")
    root = Path(__file__).resolve().parents[2]
    return RegisteredToolBundle(
        name=name,
        tools=("read", "bash", "edit", "write", "index_video",
               "read_video_sequence", "read_multiframe", "read_crop",
               "semantic_crop"),
        extensions=(root / "agent" / "pi_ext" / "vistr_video_tools.ts",),
    )
