"""Thin benchmark adapters around the external SkillOpt training engine."""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from agent.runtime import AgentConfig, AgentItem, AgentRunner
from skillopt.config import flatten_config, load_config
from skillopt.datasets.base import BatchSpec, SplitDataLoader
from skillopt.engine.trainer import ReflACTTrainer
from skillopt.envs.base import EnvAdapter
from skillopt.envs.docvqa.adapter import DocVQAAdapter
from skillopt.model import configure_azure_openai, configure_openai_compatible


def _resolve(base: Path, value: object, name: str) -> Path:
    if not value:
        raise ValueError(f"Missing {name}")
    path = Path(str(value)).expanduser()
    return (base / path).resolve() if not path.is_absolute() else path.resolve()


def _history_length(path: Path) -> int:
    if not path.is_file():
        return 0
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    return len(value) if isinstance(value, list) else 0


def _runtime_origins(out_root: Path) -> dict[str, Any]:
    path = out_root / "runtime_state.json"
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _trajectory_context(
    out_root: Path, out_dir: Path, steps_per_epoch: int,
) -> dict[str, Any]:
    """Describe one SkillOpt rollout using its trainer-owned output path."""
    relative = out_dir.resolve().relative_to(out_root.resolve())
    parts = relative.parts
    stage = "rollout" if relative == Path(".") else relative.as_posix().replace("/", "-")
    context: dict[str, Any] = {
        "split": "unknown",
        "stage": stage,
        "epoch": None,
        "step": None,
        "batch": None,
        "skill_origin": None,
    }
    origins = _runtime_origins(out_root)

    if not parts:
        return context
    if parts[0] == "selection_eval_baseline":
        context.update(split="val", stage="baseline-selection", skill_origin="initial_skill")
    elif parts[0] == "final_selection_eval":
        context.update(
            split="val", stage="final-selection",
            skill_origin=origins.get("current_origin"),
        )
    elif parts[0] == "test_eval_baseline":
        context.update(split="test", stage="baseline-test", skill_origin="initial_skill")
    elif parts[0] == "test_eval":
        context.update(
            split="test", stage="best-skill-test",
            skill_origin=origins.get("best_origin"),
        )
    elif parts[0] == "test_eval_final":
        context.update(
            split="test", stage="final-skill-test",
            skill_origin=origins.get("current_origin"),
        )
    elif parts[0] == "steps" and len(parts) >= 3:
        step = int(parts[1].removeprefix("step_"))
        epoch = (step - 1) // max(steps_per_epoch, 1) + 1
        stage = "candidate-selection" if parts[-1] == "selection_eval" else "fast-rollout"
        context.update(
            split="val" if stage == "candidate-selection" else "train",
            stage=stage,
            epoch=epoch,
            step=step,
            batch=(
                int(parts[2].removeprefix("batch_"))
                if parts[2].startswith("batch_") else None
            ),
            skill_origin=f"step_{step:04d}" if stage == "candidate-selection" else None,
        )
    elif parts[0] in {"slow_update", "meta_skill"} and len(parts) >= 3:
        epoch = int(parts[1].removeprefix("epoch_"))
        branch = parts[2]
        suffix = "-".join(value.replace("_", "-") for value in parts[3:])
        stage = f"{parts[0].replace('_', '-')}-{branch.replace('_', '-')}"
        if suffix:
            stage += f"-{suffix}"
        split_name = "val" if branch == "selection_eval" else "train"
        context.update(split=split_name, stage=stage, epoch=epoch)
    return context


def _trajectory_run_id(context: dict[str, Any]) -> str:
    parts = [str(context["split"])]
    if context.get("epoch") is not None:
        parts.append(f"epoch-{int(context['epoch']):02d}")
    if context.get("step") is not None:
        parts.append(f"step-{int(context['step']):04d}")
    if context.get("batch") is not None:
        parts.append(f"batch-{int(context['batch']):02d}")
    parts.append(str(context["stage"]))
    if context.get("skill_origin"):
        origin = str(context["skill_origin"]).replace("_", "-")
        parts.append(f"origin-{origin}")
    return "__".join(parts)


def _existing_trajectory_root(out_root: Path) -> Path | None:
    """Recover the native root used by an older/partial run for safe resume."""
    source_path = next(out_root.glob("**/predictions/*/source_trajectory.json"), None)
    if source_path is None:
        return None
    try:
        source = json.loads(source_path.read_text(encoding="utf-8"))
        trajectory_dir = Path(str(source["trajectory_dir"])).resolve()
    except (KeyError, OSError, json.JSONDecodeError):
        return None
    return trajectory_dir.parents[1]


def _existing_native_run_id(out_dir: Path) -> str | None:
    source_path = next(out_dir.glob("predictions/*/source_trajectory.json"), None)
    if source_path is None:
        return None
    try:
        source = json.loads(source_path.read_text(encoding="utf-8"))
        return Path(str(source["trajectory_dir"])).resolve().parent.name
    except (KeyError, OSError, json.JSONDecodeError):
        return None


def _record_trajectory_group(
    *,
    out_root: Path,
    out_dir: Path,
    run_id: str,
    context: dict[str, Any],
    native_group: Path,
    item_ids: list[str],
) -> Path:
    """Expose a native group inside the experiment and update its index."""
    browse_root = out_root / "trajectories"
    browse_root.mkdir(parents=True, exist_ok=True)
    browse_group = browse_root / run_id
    if browse_group.resolve() != native_group.resolve():
        if browse_group.is_symlink():
            if browse_group.resolve() != native_group.resolve():
                raise RuntimeError(f"Trajectory link targets a different group: {browse_group}")
        elif browse_group.exists():
            raise RuntimeError(f"Trajectory browse path already exists: {browse_group}")
        else:
            relative_target = os.path.relpath(native_group, browse_group.parent)
            browse_group.symlink_to(relative_target, target_is_directory=True)

    index_path = out_root / "trajectory_index.json"
    index: dict[str, Any] = {"version": 1, "experiment_dir": str(out_root), "groups": {}}
    if index_path.is_file():
        current = json.loads(index_path.read_text(encoding="utf-8"))
        if isinstance(current, dict) and isinstance(current.get("groups"), dict):
            index = current
    index["groups"][run_id] = {
        **context,
        "rollout_output_dir": str(out_dir),
        "trajectory_dir": str(browse_group),
        "native_trajectory_dir": str(native_group),
        "item_count": len(item_ids),
        "item_ids": item_ids,
    }
    index_path.write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return browse_group


def index_existing_trajectories(out_root: Path, *, steps_per_epoch: int) -> dict[str, Any]:
    """Backfill experiment-local links and metadata for an existing ViSTR run."""
    out_root = out_root.resolve()
    grouped: dict[Path, list[Path]] = {}
    for source_path in out_root.glob("**/predictions/*/source_trajectory.json"):
        grouped.setdefault(source_path.parents[2], []).append(source_path)

    for out_dir, source_paths in sorted(grouped.items(), key=lambda item: str(item[0])):
        context = _trajectory_context(out_root, out_dir, steps_per_epoch)
        run_id = _trajectory_run_id(context)
        sources = [json.loads(path.read_text(encoding="utf-8")) for path in source_paths]
        native_groups = {
            Path(str(source["trajectory_dir"])).resolve().parent for source in sources
        }
        if len(native_groups) != 1:
            raise RuntimeError(f"Mixed native trajectory groups in {out_dir}")
        native_group = native_groups.pop()
        item_ids = sorted((path.parent.name for path in source_paths), key=lambda x: (len(x), x))
        browse_group = _record_trajectory_group(
            out_root=out_root,
            out_dir=out_dir,
            run_id=run_id,
            context=context,
            native_group=native_group,
            item_ids=item_ids,
        )
        for path, source in zip(source_paths, sources):
            source.update({
                "experiment_trajectory_dir": str(browse_group / path.parent.name),
                "run_context": context,
            })
            path.write_text(
                json.dumps(source, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        results_path = out_dir / "results.jsonl"
        if results_path.is_file():
            rows = [
                json.loads(line) for line in results_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            for row in rows:
                row["experiment_trajectory_dir"] = str(browse_group / str(row["id"]))
                row["run_context"] = context
            results_path.write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                encoding="utf-8",
            )
    index_path = out_root / "trajectory_index.json"
    return json.loads(index_path.read_text(encoding="utf-8"))


def _train_preserving_completed_summary(cfg: dict, adapter: EnvAdapter) -> dict:
    """Keep the original summary when a completed run resumes with no new step."""
    out_root = Path(str(cfg["out_root"]))
    summary_path = out_root / "summary.json"
    history_path = out_root / "history.json"
    prior_summary = summary_path.read_bytes() if summary_path.is_file() else None
    prior_steps = _history_length(history_path)

    result = ReflACTTrainer(cfg, adapter).train()

    if (
        prior_summary is not None
        and prior_steps > 0
        and _history_length(history_path) == prior_steps
    ):
        summary_path.write_bytes(prior_summary)
    return result


def _configure_skillopt_models(cfg: dict, agent_config: AgentConfig) -> None:
    provider = agent_config.providers[agent_config.policy.provider]
    base_url = agent_config.env_values[provider.base_url_env]
    api_key = agent_config.env_values[provider.api_key_env]
    hostname = (urlparse(base_url).hostname or "").lower()
    if hostname == "api.openai.com":
        cfg["model_backend"] = "azure_openai"
        cfg["optimizer_backend"] = "openai_chat"
        cfg["target_backend"] = "openai_chat"
        cfg["azure_openai_endpoint"] = base_url
        cfg["azure_openai_auth_mode"] = "openai_compatible"
        configure_azure_openai(
            endpoint=base_url,
            api_key=api_key,
            auth_mode="openai_compatible",
        )
        return

    cfg["model_backend"] = "openai_compatible"
    cfg["optimizer_backend"] = "openai_compatible"
    cfg["target_backend"] = "openai_compatible"
    configure_openai_compatible(
        optimizer_base_url=base_url,
        optimizer_api_key=api_key,
        optimizer_model=agent_config.policy.id,
        target_base_url=base_url,
        target_api_key=api_key,
        target_model=agent_config.policy.id,
        max_tokens=int(cfg.get("max_completion_tokens", 16384)),
    )


class ViSTRSkillOptDataLoader(SplitDataLoader):
    """Filter ViSTR by user IDs, then use SkillOpt's native ratio splitter."""

    def __init__(self, *, dataset_root: Path, id_file: Path, **kwargs: Any) -> None:
        self.dataset_root = dataset_root
        self.id_file = id_file
        self._selected_ids: list[str] = []
        self._dataset_sha256 = ""
        super().__init__(data_path=str(dataset_root / "data.json"), **kwargs)

    def _load_selected_ids(self) -> list[str]:
        raw = json.loads(self.id_file.read_text(encoding="utf-8"))
        if not isinstance(raw, list) or not raw:
            raise ValueError("dataset.id_file must contain a non-empty JSON array")
        ids = [str(value) for value in raw]
        if len(ids) != len(set(ids)):
            raise ValueError("dataset.id_file contains duplicate ViSTR IDs")
        return ids

    def load_raw_items(self, data_path: str) -> list[dict]:
        data_file = Path(data_path)
        rows = json.loads(data_file.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            raise ValueError(f"Expected a JSON array in {data_file}")
        by_id = {str(row["id"]): row for row in rows}
        missing = [item_id for item_id in self._selected_ids if item_id not in by_id]
        if missing:
            preview = ", ".join(missing[:10])
            raise ValueError(f"Unknown ViSTR IDs in dataset.id_file: {preview}")
        return [self._normalize(by_id[item_id]) for item_id in self._selected_ids]

    def setup(self, cfg: dict) -> None:
        self._selected_ids = self._load_selected_ids()
        data_file = self.dataset_root / "data.json"
        self._dataset_sha256 = hashlib.sha256(data_file.read_bytes()).hexdigest()
        selected_hash = hashlib.sha256(
            json.dumps(self._selected_ids, separators=(",", ":")).encode()
        ).hexdigest()
        integration = cfg.get("integration", {})
        skillopt_commit = (
            str(integration.get("expected_commit") or "")
            if isinstance(integration, dict) else ""
        )

        split_dir = Path(self._resolve_split_output_dir(cfg))
        manifest_path = split_dir / "split_manifest.json"
        expected = {
            "selected_ids_sha256": selected_hash,
            "dataset_sha256": self._dataset_sha256,
            "split_ratio": self.split_ratio,
            "split_seed": self.split_seed,
            "skillopt_commit": skillopt_commit,
        }
        if manifest_path.is_file():
            current = json.loads(manifest_path.read_text(encoding="utf-8"))
            if any(current.get(key) != value for key, value in expected.items()):
                raise RuntimeError(
                    f"Generated split manifest does not match this run: {manifest_path}"
                )

        super().setup(cfg)
        manifest_path = Path(self.split_dir) / "split_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.update({
            **expected,
            "selected_id_count": len(self._selected_ids),
            "selected_ids": self._selected_ids,
        })
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _normalize(self, row: dict) -> dict:
        return {
            "id": str(row["id"]),
            "video": str(row["video"]),
            "question": str(row["direct_prompting"]),
            "options": [str(value) for value in row["options"]],
            "ground_truth": str(row["answer"]),
            "task_type": str(row["task"]),
            "dimension": str(row.get("dimension", "")),
        }


class ViSTRSkillOptAdapter(EnvAdapter):
    def __init__(
        self,
        *,
        runner: AgentRunner,
        dataloader: ViSTRSkillOptDataLoader,
        prompt_dir: Path,
        analyst_workers: int,
        failure_only: bool,
        minibatch_size: int,
        edit_budget: int,
        out_root: Path | None = None,
        steps_per_epoch: int = 1,
    ) -> None:
        self.runner = runner
        self.dataloader = dataloader
        self.prompt_dir = prompt_dir
        self.analyst_workers = analyst_workers
        self.failure_only = failure_only
        self.minibatch_size = minibatch_size
        self.edit_budget = edit_budget
        self.out_root = out_root.resolve() if out_root is not None else None
        self.steps_per_epoch = steps_per_epoch

    def setup(self, cfg: dict) -> None:
        super().setup(cfg)
        self.dataloader.setup(cfg)
        train_size = int(cfg.get("train_size", 0) or len(self.dataloader.train_items))
        self.steps_per_epoch = math.ceil(
            train_size / (int(cfg["batch_size"]) * int(cfg["accumulation"]))
        )

    def get_dataloader(self) -> ViSTRSkillOptDataLoader:
        return self.dataloader

    def build_env_from_batch(self, batch: BatchSpec, **kwargs: Any) -> list[dict]:
        return list(batch.payload or [])

    def build_train_env(self, batch_size: int, seed: int, **kwargs: Any) -> list[dict]:
        batch = self.dataloader.build_train_batch(batch_size=batch_size, seed=seed, **kwargs)
        return self.build_env_from_batch(batch)

    def build_eval_env(self, env_num: int, split: str, seed: int, **kwargs: Any) -> list[dict]:
        batch = self.dataloader.build_eval_batch(
            env_num=env_num, split=split, seed=seed, **kwargs
        )
        return self.build_env_from_batch(batch)

    def rollout(
        self, env_manager: list[dict], skill_content: str, out_dir: str, **kwargs: Any
    ) -> list[dict]:
        rollout_dir = Path(out_dir).resolve()
        out_root = self.out_root or rollout_dir
        context = _trajectory_context(out_root, rollout_dir, self.steps_per_epoch)
        browse_run_id = _trajectory_run_id(context)
        native_run_id = _existing_native_run_id(rollout_dir) or browse_run_id
        items = [self._agent_item(row) for row in env_manager]
        records = self.runner.rollout(
            items, skill_content=skill_content, run_id=native_run_id
        )
        predictions = rollout_dir / "predictions"
        predictions.mkdir(parents=True, exist_ok=True)
        native_groups = {
            Path(str(record.trajectory_dir)).resolve().parent for record in records
        }
        if len(native_groups) != 1:
            raise RuntimeError(f"Mixed native trajectory groups in {rollout_dir}")
        browse_group = _record_trajectory_group(
            out_root=out_root,
            out_dir=rollout_dir,
            run_id=browse_run_id,
            context=context,
            native_group=native_groups.pop(),
            item_ids=[item.id for item in items],
        )
        results: list[dict] = []
        for item, record in zip(items, records):
            item_dir = predictions / item.id
            item_dir.mkdir(parents=True, exist_ok=True)
            conversation = self._conversation(record, item)
            (item_dir / "conversation.json").write_text(
                json.dumps(conversation, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            target_prompt = f"{item.question}\n\nOptions: {' / '.join(item.options)}"
            (item_dir / "target_user_prompt.txt").write_text(target_prompt, encoding="utf-8")
            (item_dir / "source_trajectory.json").write_text(
                json.dumps({
                    "trajectory_dir": record.trajectory_dir,
                    "conversation_path": record.conversation_path,
                    "session_jsonl": record.session_jsonl,
                    "session_html": record.session_html,
                    "experiment_trajectory_dir": str(browse_group / item.id),
                    "run_context": context,
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            results.append({
                "id": record.id,
                "hard": float(record.hard or 0),
                "soft": float(record.soft or 0),
                "n_turns": record.n_turns,
                "fail_reason": record.fail_reason,
                "task_type": record.task_type,
                "task_description": record.task_description,
                "question": record.question,
                "predicted_answer": record.predicted_answer or "",
                "target_user_prompt": target_prompt,
                "trajectory_dir": record.trajectory_dir,
                "experiment_trajectory_dir": str(browse_group / item.id),
                "run_context": context,
                "conversation_path": record.conversation_path,
                "session_html": record.session_html,
                "agent_ok": record.agent_ok,
                "attempts": len(record.attempts),
                "timeout_attempts": sum(
                    1 for attempt in record.attempts
                    if "timeout" in str(attempt.process_error or "").lower()
                ),
            })
        (rollout_dir / "results.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in results),
            encoding="utf-8",
        )
        return results

    def get_task_types(self) -> list[str]:
        return sorted({
            str(item.get("task_type") or "unknown")
            for split in (self.dataloader.train_items,
                          self.dataloader.val_items,
                          self.dataloader.test_items)
            for item in split
        })

    def get_error_minibatch_prompt(self) -> str:
        return (self.prompt_dir / "analyst_error.md").read_text(encoding="utf-8")

    def get_success_minibatch_prompt(self) -> str:
        return (self.prompt_dir / "analyst_success.md").read_text(encoding="utf-8")

    def _agent_item(self, row: dict) -> AgentItem:
        return AgentItem(
            id=str(row["id"]),
            video_path=(self.dataloader.dataset_root / str(row["video"])).resolve(),
            question=str(row["question"]),
            options=tuple(str(value) for value in row["options"]),
            ground_truth=str(row["ground_truth"]),
            task_type=str(row["task_type"]),
            metadata={"dimension": str(row.get("dimension", "")),
                      "video": str(row["video"])},
        )

    @staticmethod
    def _conversation(record: Any, item: AgentItem) -> list[dict]:
        if record.conversation_path and Path(record.conversation_path).is_file():
            conversation = json.loads(
                Path(record.conversation_path).read_text(encoding="utf-8")
            )
            if isinstance(conversation, list):
                return conversation
        return [
            {"role": "user", "content": f"{item.question}\n\nOptions: {' / '.join(item.options)}"},
            {"role": "system", "content": (
                "[EXECUTION RESULT]\n"
                f"Error: {record.fail_reason or 'No Pi conversation was produced'}"
            )},
        ]


def run_training(config_path: Path, *, overrides: list[str], smoke: bool) -> dict:
    structured = load_config(str(config_path), overrides=overrides)
    cfg = flatten_config(structured)
    integration = structured.get("integration", {})
    dataset = structured.get("dataset", {})
    if not isinstance(integration, dict) or not isinstance(dataset, dict):
        raise ValueError("SkillOpt config requires integration and dataset mappings")
    base = config_path.parent

    agent_config_path = _resolve(
        base, integration.get("agent_config"), "integration.agent_config"
    )
    agent_config = AgentConfig.from_yaml(agent_config_path)
    if (
        cfg.get("optimizer_model") != "inherit_policy"
        or cfg.get("target_model") != "inherit_policy"
    ):
        raise ValueError(
            "model.optimizer and model.target must be inherit_policy; "
            "the S2.8 agent YAML owns model selection"
        )

    env_name = str(cfg.get("env") or "").strip().lower()
    if env_name not in {"vistr", "docvqa"}:
        raise ValueError(f"Unsupported SkillOpt environment: {env_name!r}")
    if smoke:
        cfg["out_root"] = str(cfg.get("out_root") or "").rstrip("/") + "_smoke"
    cfg["out_root"] = str(_resolve(base, cfg.get("out_root"), "env.out_root"))
    cfg["skill_init"] = str(_resolve(base, cfg.get("skill_init"), "env.skill_init"))
    cfg["optimizer_model"] = agent_config.policy.id
    cfg["target_model"] = agent_config.policy.id
    cfg["smoke"] = smoke

    optimizer_env_names = (
        "OPENAI_COMPATIBLE_MAX_TOKENS",
        "OPTIMIZER_OPENAI_COMPATIBLE_BASE_URL",
        "OPTIMIZER_OPENAI_COMPATIBLE_API_KEY",
        "OPTIMIZER_OPENAI_COMPATIBLE_MODEL",
        "TARGET_OPENAI_COMPATIBLE_BASE_URL",
        "TARGET_OPENAI_COMPATIBLE_API_KEY",
        "TARGET_OPENAI_COMPATIBLE_MODEL",
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_API_VERSION",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_AUTH_MODE",
        "OPTIMIZER_AZURE_OPENAI_ENDPOINT",
        "OPTIMIZER_AZURE_OPENAI_API_VERSION",
        "OPTIMIZER_AZURE_OPENAI_API_KEY",
        "OPTIMIZER_AZURE_OPENAI_AUTH_MODE",
        "TARGET_AZURE_OPENAI_ENDPOINT",
        "TARGET_AZURE_OPENAI_API_VERSION",
        "TARGET_AZURE_OPENAI_API_KEY",
        "TARGET_AZURE_OPENAI_AUTH_MODE",
        "OPTIMIZER_BACKEND",
        "TARGET_BACKEND",
        "OPTIMIZER_DEPLOYMENT",
        "TARGET_DEPLOYMENT",
        "AZURE_OPENAI_DEPLOYMENT",
    )
    previous_env = {name: os.environ.get(name) for name in optimizer_env_names}

    def configure_models() -> None:
        _configure_skillopt_models(cfg, agent_config)

    try:
        if env_name == "docvqa":
            split_dir = _resolve(
                base,
                dataset.get("split_dir") or cfg.get("split_dir"),
                "dataset.split_dir",
            )
            if not all((split_dir / name / "items.csv").is_file()
                       for name in ("train", "val", "test")):
                raise FileNotFoundError(
                    f"Materialized DocVQA split not found: {split_dir}; "
                    "run agent.skillopt.prepare_comparison first"
                )
            cfg["split_dir"] = str(split_dir)
            configure_models()
            adapter = DocVQAAdapter(
                split_dir=str(split_dir),
                split_mode="split_dir",
                max_turns=int(cfg.get("max_turns", 1)),
                exec_timeout=int(cfg.get("exec_timeout", 120)),
                workers=int(cfg.get("workers", 16)),
                analyst_workers=int(cfg["analyst_workers"]),
                failure_only=bool(cfg["failure_only"]),
                minibatch_size=int(cfg["minibatch_size"]),
                edit_budget=int(cfg["edit_budget"]),
                seed=int(cfg["seed"]),
                limit=int(cfg.get("limit", 0)),
                image_detail=str(cfg.get("image_detail", "auto")),
                max_completion_tokens=int(cfg.get("max_completion_tokens", 16384)),
            )
            return _train_preserving_completed_summary(cfg, adapter)

        id_file = _resolve(base, dataset.get("id_file"), "dataset.id_file")
        if not id_file.is_file():
            raise FileNotFoundError(f"ViSTR ID file not found: {id_file}")
        if cfg.get("split_mode") != "ratio":
            raise ValueError("ViSTR SkillOpt integration requires env.split_mode=ratio")
        split_output = cfg.get("split_output_dir") or str(
            Path(cfg["out_root"]) / "_generated_splits"
        )
        cfg["split_output_dir"] = str(
            _resolve(base, split_output, "env.split_output_dir")
        )
        cfg["data_path"] = str(agent_config.dataset.root / "data.json")
        cfg["workers"] = agent_config.agent.workers
        out_root = Path(cfg["out_root"])
        trajectory_root = _existing_trajectory_root(out_root) or out_root / "trajectories"
        agent_config = replace(
            agent_config,
            artifacts=replace(agent_config.artifacts, trajectory_root=trajectory_root),
        )
        dataloader = ViSTRSkillOptDataLoader(
            dataset_root=agent_config.dataset.root,
            id_file=id_file,
            split_mode="ratio",
            split_ratio=str(cfg.get("split_ratio", "2:1:7")),
            split_seed=int(cfg.get("split_seed", 42)),
            split_output_dir=cfg["split_output_dir"],
            seed=int(cfg["seed"]),
            limit=int(cfg.get("limit", 0)),
        )
        with AgentRunner(agent_config) as runner:
            configure_models()
            adapter = ViSTRSkillOptAdapter(
                runner=runner,
                dataloader=dataloader,
                prompt_dir=Path(__file__).with_name("prompts"),
                analyst_workers=int(cfg["analyst_workers"]),
                failure_only=bool(cfg["failure_only"]),
                minibatch_size=int(cfg["minibatch_size"]),
                edit_budget=int(cfg["edit_budget"]),
                out_root=out_root,
                steps_per_epoch=int(cfg.get("steps_per_epoch", 1)),
            )
            return _train_preserving_completed_summary(cfg, adapter)
    finally:
        for name, value in previous_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
