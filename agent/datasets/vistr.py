"""ViSTR-Bench adapter for the generic agent item contract."""

from __future__ import annotations

import json
from pathlib import Path

from agent.runtime.config import DatasetConfig
from agent.runtime.contracts import AgentItem


class ViSTRAdapter:
    def __init__(self, config: DatasetConfig):
        self.config = config

    def load(self, split: str = "dev", tasks: list[str] | None = None,
             limit: int | None = None, per_task: int | None = None,
             ids: list[str] | None = None) -> list[AgentItem]:
        if split not in {"dev", "eval", "all"}:
            raise ValueError("split must be dev, eval, or all")
        data_path = self.config.root / "data.json"
        data = json.loads(data_path.read_text(encoding="utf-8"))
        by_id = {str(row["id"]): row for row in data}
        if split == "all":
            samples = data
        else:
            split_cfg = json.loads(self.config.split_config.read_text(encoding="utf-8"))
            selected: list[str] = []
            for task_ids in split_cfg.values():
                selected.extend(str(v) for v in task_ids.get(split, []))
            samples = [by_id[sid] for sid in selected if sid in by_id]
        if tasks:
            wanted = set(tasks)
            samples = [row for row in samples if row["task"] in wanted]
        if ids:
            wanted_ids = {str(v) for v in ids}
            samples = [row for row in samples if str(row["id"]) in wanted_ids]
        if per_task:
            grouped: dict[str, list[dict]] = {}
            for row in samples:
                grouped.setdefault(row["task"], []).append(row)
            picked: list[dict] = []
            for task in sorted(grouped):
                group = grouped[task]
                count = min(per_task, len(group))
                indices = [round(i * (len(group) - 1) / max(count - 1, 1))
                           for i in range(count)]
                picked.extend(group[i] for i in sorted(set(indices)))
            samples = picked
        if limit:
            samples = samples[:limit]
        return [self._normalize(row) for row in samples]

    def _normalize(self, row: dict) -> AgentItem:
        return AgentItem(
            id=str(row["id"]),
            video_path=(self.config.root / row["video"]).resolve(),
            question=row["direct_prompting"],
            options=tuple(str(v) for v in row["options"]),
            ground_truth=str(row["answer"]),
            task_type=str(row["task"]),
            metadata={"dimension": row.get("dimension", ""),
                      "video": row.get("video", "")},
        )
