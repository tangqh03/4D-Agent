#!/usr/bin/env python
"""Offline tests for the ViSTR-to-SkillOpt bridge."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SKILLOPT_ROOT = ROOT.parent / "SkillOpt"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SKILLOPT_ROOT))

from agent.skillopt.integration import (
    ViSTRSkillOptAdapter,
    ViSTRSkillOptDataLoader,
    _configure_skillopt_models,
)
from skillopt.config import flatten_config, load_config
from skillopt.engine.trainer import ReflACTTrainer


class BridgeFixture:
    def __init__(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="skillopt_bridge_test_")
        self.root = Path(self.tmp.name)
        self.dataset = self.root / "dataset"
        self.dataset.mkdir()
        rows = []
        for item_id in range(1, 11):
            video = f"video-{item_id}.mp4"
            (self.dataset / video).write_bytes(b"video")
            rows.append({
                "id": item_id,
                "video": video,
                "direct_prompting": f"Question {item_id}?",
                "options": ["Yes", "No"],
                "answer": "Yes",
                "task": "Vehicle_Movement",
                "dimension": "Motion_Perception",
            })
        (self.dataset / "data.json").write_text(json.dumps(rows), encoding="utf-8")
        self.ids = self.root / "ids.json"
        self.ids.write_text(json.dumps(list(range(1, 11))), encoding="utf-8")
        self.split_dir = self.root / "splits"

    def loader(self) -> ViSTRSkillOptDataLoader:
        return ViSTRSkillOptDataLoader(
            dataset_root=self.dataset,
            id_file=self.ids,
            split_mode="ratio",
            split_ratio="2:1:7",
            split_seed=42,
            split_output_dir=str(self.split_dir),
            seed=42,
            limit=0,
        )

    def close(self) -> None:
        self.tmp.cleanup()


class DataLoaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = BridgeFixture()

    def tearDown(self) -> None:
        self.fx.close()

    def test_ratio_split_is_deterministic_and_manifested(self) -> None:
        loader = self.fx.loader()
        loader.setup({"out_root": str(self.fx.root / "out"), "env": "vistr",
                      "integration": {"expected_commit": "test-commit"}})
        self.assertEqual(
            (len(loader.train_items), len(loader.val_items), len(loader.test_items)),
            (2, 1, 7),
        )
        first = [[item["id"] for item in split] for split in (
            loader.train_items, loader.val_items, loader.test_items
        )]
        second = self.fx.loader()
        second.setup({"out_root": str(self.fx.root / "out"), "env": "vistr",
                      "integration": {"expected_commit": "test-commit"}})
        self.assertEqual(first, [[item["id"] for item in split] for split in (
            second.train_items, second.val_items, second.test_items
        )])

        manifest = json.loads((self.fx.split_dir / "split_manifest.json").read_text())
        expected_dataset_hash = hashlib.sha256(
            (self.fx.dataset / "data.json").read_bytes()
        ).hexdigest()
        self.assertEqual(manifest["dataset_sha256"], expected_dataset_hash)
        self.assertEqual(manifest["selected_id_count"], 10)
        self.assertEqual(manifest["counts"], {"train": 2, "val": 1, "test": 7})
        self.assertEqual(manifest["skillopt_commit"], "test-commit")

    def test_invalid_id_pool_fails_before_splitting(self) -> None:
        self.fx.ids.write_text('["1", "missing"]', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Unknown ViSTR IDs"):
            self.fx.loader().setup({"out_root": str(self.fx.root / "out"), "env": "vistr"})

    def test_changed_id_pool_rejects_existing_manifest(self) -> None:
        self.fx.loader().setup({"out_root": str(self.fx.root / "out"), "env": "vistr"})
        self.fx.ids.write_text(json.dumps(list(range(1, 10))), encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "manifest does not match"):
            self.fx.loader().setup({"out_root": str(self.fx.root / "out"), "env": "vistr"})


class FakeRunner:
    def __init__(self, conversation_path: Path, trajectory_dir: Path) -> None:
        self.conversation_path = conversation_path
        self.trajectory_dir = trajectory_dir
        self.calls = []

    def rollout(self, items, *, skill_content, run_id):
        self.calls.append((items, skill_content, run_id))
        item = items[0]
        return [SimpleNamespace(
            id=item.id,
            hard=1,
            soft=1.0,
            n_turns=1,
            fail_reason="",
            task_type=item.task_type,
            task_description=item.question,
            question=item.question,
            predicted_answer="Yes",
            trajectory_dir=str(self.trajectory_dir),
            conversation_path=str(self.conversation_path),
            session_jsonl=[str(self.trajectory_dir / "session.jsonl")],
            session_html=[str(self.trajectory_dir / "session.html")],
            agent_ok=True,
            attempts=[],
        )]


class AdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = BridgeFixture()
        self.loader = self.fx.loader()
        self.loader.setup({"out_root": str(self.fx.root / "out"), "env": "vistr"})

    def tearDown(self) -> None:
        self.fx.close()

    def test_rollout_projects_native_trajectory_for_skillopt(self) -> None:
        trajectory = self.fx.root / "trajectory"
        trajectory.mkdir()
        conversation_path = trajectory / "conversation.json"
        conversation_path.write_text(json.dumps([
            {"type": "tool_call", "cmd": "read_multiframe({})", "obs": "frames"},
            {"role": "system", "content": "[EVALUATION RESULT]\nHard: 1"},
        ]), encoding="utf-8")
        runner = FakeRunner(conversation_path, trajectory)
        adapter = ViSTRSkillOptAdapter(
            runner=runner,
            dataloader=self.loader,
            prompt_dir=ROOT / "agent" / "skillopt" / "prompts",
            analyst_workers=16,
            failure_only=False,
            minibatch_size=8,
            edit_budget=4,
        )
        out_dir = self.fx.root / "rollout"
        results = adapter.rollout([self.loader.train_items[0]], "# Candidate", str(out_dir))

        self.assertEqual(results[0]["hard"], 1.0)
        self.assertEqual(runner.calls[0][1], "# Candidate")
        self.assertTrue(runner.calls[0][2].startswith("skillopt-"))
        projected = json.loads(
            (out_dir / "predictions" / results[0]["id"] / "conversation.json").read_text()
        )
        self.assertEqual(projected[0]["cmd"], "read_multiframe({})")
        source = json.loads(
            (out_dir / "predictions" / results[0]["id"] / "source_trajectory.json").read_text()
        )
        self.assertEqual(source["trajectory_dir"], str(trajectory))


class ConfigTests(unittest.TestCase):
    def test_docvqa_training_hyperparameters_are_inherited(self) -> None:
        config = flatten_config(load_config(str(
            ROOT / "configs" / "skillopt" / "vistr_docvqa.yaml"
        )))
        expected = {
            "num_epochs": 4,
            "batch_size": 40,
            "accumulation": 1,
            "seed": 42,
            "minibatch_size": 8,
            "merge_batch_size": 8,
            "analyst_workers": 16,
            "failure_only": False,
            "edit_budget": 4,
            "min_edit_budget": 2,
            "lr_scheduler": "cosine",
            "skill_update_mode": "patch",
            "use_gate": True,
            "sel_env_num": 0,
            "test_env_num": 0,
            "eval_test": True,
            "use_slow_update": True,
            "slow_update_samples": 20,
            "use_meta_skill": True,
        }
        self.assertEqual({key: config[key] for key in expected}, expected)
        self.assertEqual(config["split_ratio"], "2:1:7")
        self.assertEqual(config["split_seed"], 42)

    def test_official_openai_uses_skillopt_openai_chat_backend(self) -> None:
        agent_config = SimpleNamespace(
            policy=SimpleNamespace(provider="openai", id="gpt-5.5"),
            providers={"openai": SimpleNamespace(
                base_url_env="OPENAI_BASE_URL", api_key_env="OPENAI_API_KEY"
            )},
            env_values={
                "OPENAI_BASE_URL": "https://api.openai.com/v1",
                "OPENAI_API_KEY": "test-key",
            },
        )
        cfg = {"max_completion_tokens": 16384}
        with mock.patch("agent.skillopt.integration.configure_azure_openai") as configure:
            _configure_skillopt_models(cfg, agent_config)
        self.assertEqual(cfg["optimizer_backend"], "openai_chat")
        self.assertEqual(cfg["target_backend"], "openai_chat")
        self.assertEqual(cfg["azure_openai_auth_mode"], "openai_compatible")
        configure.assert_called_once_with(
            endpoint="https://api.openai.com/v1",
            api_key="test-key",
            auth_mode="openai_compatible",
        )

    def test_non_openai_provider_keeps_generic_backend(self) -> None:
        agent_config = SimpleNamespace(
            policy=SimpleNamespace(provider="deepseek", id="vision-model"),
            providers={"deepseek": SimpleNamespace(
                base_url_env="BASE_URL", api_key_env="API_KEY"
            )},
            env_values={"BASE_URL": "https://api.deepseek.com", "API_KEY": "key"},
        )
        cfg = {"max_completion_tokens": 16384}
        with mock.patch(
            "agent.skillopt.integration.configure_openai_compatible"
        ) as configure:
            _configure_skillopt_models(cfg, agent_config)
        self.assertEqual(cfg["optimizer_backend"], "openai_compatible")
        self.assertEqual(cfg["target_backend"], "openai_compatible")
        configure.assert_called_once()


class LoopFakeRunner:
    def __init__(self, root: Path) -> None:
        self.root = root

    def rollout(self, items, *, skill_content, run_id):
        records = []
        for item in items:
            trajectory = self.root / run_id / item.id
            trajectory.mkdir(parents=True, exist_ok=True)
            conversation_path = trajectory / "conversation.json"
            hard = int("Verify decisive evidence" in skill_content)
            conversation_path.write_text(json.dumps([
                {"role": "user", "content": item.question},
                {"type": "tool_call", "cmd": "read_multiframe({})", "obs": "frames"},
                {"role": "system", "content": f"[EVALUATION RESULT]\nHard: {hard}"},
            ]), encoding="utf-8")
            records.append(SimpleNamespace(
                id=item.id,
                hard=hard,
                soft=float(hard),
                n_turns=1,
                fail_reason="" if hard else "Wrong answer",
                task_type=item.task_type,
                task_description=item.question,
                question=item.question,
                predicted_answer="Yes" if hard else "No",
                trajectory_dir=str(trajectory),
                conversation_path=str(conversation_path),
                session_jsonl=[],
                session_html=[],
                agent_ok=True,
                attempts=[],
            ))
        return records


class TrainerIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = BridgeFixture()

    def tearDown(self) -> None:
        self.fx.close()

    def test_one_native_reflact_step_accepts_improving_skill(self) -> None:
        skill = self.fx.root / "initial.md"
        skill.write_text("# Initial\nInspect the video.\n", encoding="utf-8")
        out_root = self.fx.root / "training"
        cfg = flatten_config(load_config(str(
            ROOT / "configs" / "skillopt" / "vistr_docvqa.yaml"
        )))
        cfg.update({
            "out_root": str(out_root),
            "skill_init": str(skill),
            "num_epochs": 1,
            "train_size": 0,
            "batch_size": 2,
            "accumulation": 1,
            "minibatch_size": 2,
            "merge_batch_size": 2,
            "analyst_workers": 1,
            "failure_only": True,
            "use_slow_update": False,
            "use_meta_skill": False,
            "sel_env_num": 1,
            "eval_test": False,
            "model_backend": "openai_compatible",
            "optimizer_backend": "openai_compatible",
            "target_backend": "openai_compatible",
            "optimizer_model": "fake",
            "target_model": "fake",
        })
        loader = ViSTRSkillOptDataLoader(
            dataset_root=self.fx.dataset,
            id_file=self.fx.ids,
            split_mode="ratio",
            split_ratio="2:1:7",
            split_seed=42,
            split_output_dir=str(self.fx.split_dir),
            seed=42,
            limit=0,
        )
        adapter = ViSTRSkillOptAdapter(
            runner=LoopFakeRunner(self.fx.root / "trajectories"),
            dataloader=loader,
            prompt_dir=ROOT / "agent" / "skillopt" / "prompts",
            analyst_workers=1,
            failure_only=True,
            minibatch_size=2,
            edit_budget=4,
        )
        optimizer_reply = json.dumps({
            "batch_size": 2,
            "failure_summary": [{
                "failure_type": "temporal_evidence_miss",
                "count": 2,
                "description": "The decisive interval was not verified.",
            }],
            "patch": {
                "reasoning": "Require evidence verification.",
                "edits": [{"op": "append", "content": "\n## Verify decisive evidence\n"}],
            },
        })
        with mock.patch(
            "skillopt.gradient.reflect.chat_optimizer",
            return_value=(optimizer_reply, {"prompt_tokens": 1, "completion_tokens": 1}),
        ):
            summary = ReflACTTrainer(cfg, adapter).train()

        self.assertEqual(summary["best_selection_hard"], 1.0)
        self.assertIn("Verify decisive evidence", (out_root / "best_skill.md").read_text())
        history = json.loads((out_root / "history.json").read_text())
        self.assertEqual(history[0]["action"], "accept_new_best")


if __name__ == "__main__":
    unittest.main()
