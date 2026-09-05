#!/usr/bin/env python
"""Offline tests for the 100-item SkillOpt comparison experiment."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SKILLOPT_ROOT = ROOT.parent / "SkillOpt"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SKILLOPT_ROOT))

from agent.skillopt.compare_runs import compare, summarize_run
from agent.skillopt.integration import _train_preserving_completed_summary
from agent.skillopt.prepare_comparison import prepare
from skillopt.config import flatten_config, load_config
from skillopt.envs.docvqa.dataloader import DocVQADataLoader
from skillopt.optimizer.scheduler import CosineScheduler


class PreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = prepare(ROOT / "configs" / "skillopt" / "comparison_100.yaml")
        cls.data_root = ROOT / "data" / "skillopt_comparison" / "seed43"

    def test_samples_and_splits_are_fixed(self) -> None:
        self.assertEqual(self.manifest["sample_seed"], 43)
        self.assertEqual(self.manifest["split_seed"], 43)
        self.assertEqual(
            self.manifest["skillopt_commit"],
            "db46cd9ae7ce12f1dbd73c945185816aa738751d",
        )
        self.assertEqual(self.manifest["counts"], {"train": 20, "val": 10, "test": 70})
        self.assertEqual(len(self.manifest["vistr"]["ids"]), 100)
        self.assertEqual(len(self.manifest["vistr"]["task_distribution"]), 15)
        self.assertEqual(self.manifest["vistr"]["option_count_distribution"], {"2": 100})
        self.assertEqual(len(self.manifest["docvqa"]["ids"]), 100)
        self.assertEqual(self.manifest["docvqa"]["unique_images"], 100)
        for benchmark in ("vistr", "docvqa"):
            splits = self.manifest[benchmark]["splits"]
            ids = splits["train"] + splits["val"] + splits["test"]
            self.assertEqual(len(ids), 100)
            self.assertEqual(len(set(ids)), 100)

    def test_materialized_docvqa_loads_with_answers_and_unique_images(self) -> None:
        loader = DocVQADataLoader(
            split_dir=str(self.data_root / "docvqa" / "splits"),
            split_mode="split_dir",
        )
        loader.setup({})
        items = loader.train_items + loader.val_items + loader.test_items
        self.assertEqual(
            (len(loader.train_items), len(loader.val_items), len(loader.test_items)),
            (20, 10, 70),
        )
        self.assertTrue(all(item["answers"] for item in items))
        self.assertEqual(len({item["image_path"] for item in items}), 100)
        self.assertTrue(all(Path(item["image_path"]).is_file() for item in items))


class RecipeTests(unittest.TestCase):
    def test_comparison_configs_share_batch_and_update_budget(self) -> None:
        configs = []
        for name in ("vistr_comparison_100.yaml", "docvqa_comparison_100.yaml"):
            configs.append(flatten_config(load_config(str(
                ROOT / "configs" / "skillopt" / name
            ))))
        compared = (
            "num_epochs", "batch_size", "accumulation", "seed",
            "minibatch_size", "merge_batch_size", "analyst_workers",
            "failure_only", "edit_budget", "min_edit_budget", "lr_scheduler",
            "skill_update_mode", "use_gate", "sel_env_num", "test_env_num",
            "use_slow_update", "slow_update_samples", "use_meta_skill",
        )
        self.assertEqual(
            {key: configs[0][key] for key in compared},
            {key: configs[1][key] for key in compared},
        )
        self.assertEqual(configs[0]["batch_size"], 5)
        self.assertEqual(configs[0]["seed"], 43)
        steps = 4 * ((20 + 5 - 1) // 5)
        self.assertEqual(steps, 16)
        scheduler = CosineScheduler(4, 2, steps)
        self.assertEqual(
            [scheduler.step() for _ in range(steps)],
            [4, 4, 4, 4, 4, 3, 3, 3, 3, 3, 2, 2, 2, 2, 2, 2],
        )


class ReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="skillopt_compare_test_")
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_run(self, name: str, actions: list[str]) -> Path:
        root = self.root / name
        root.mkdir()
        summary = {
            "config": {"env": name, "target_model": "same-model"},
            "baseline_selection_hard": 0.4,
            "best_selection_hard": 0.6,
            "baseline_test_hard": 0.3,
            "test_hard": 0.5,
            "test_delta_hard": 0.2,
            "token_summary": {"_total": {"calls": 4, "total_tokens": 100}},
        }
        (root / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        history = []
        for index, action in enumerate(actions, 1):
            history.append({
                "step": index,
                "action": action,
                "n_patches": 0 if action.startswith("skip") else 1,
                "candidate_hash": "" if action.startswith("skip") else str(index),
                "n_edits_ranked": 0 if action.startswith("skip") else 1,
                "edit_budget": 4,
            })
        (root / "history.json").write_text(json.dumps(history), encoding="utf-8")
        rollout = root / "steps" / "step_0001" / "rollout"
        rollout.mkdir(parents=True)
        (rollout / "results.jsonl").write_text(
            json.dumps({"id": "1", "agent_ok": True, "attempts": 2,
                        "timeout_attempts": 1}) + "\n",
            encoding="utf-8",
        )
        slow = root / "slow_update" / "epoch_01"
        slow.mkdir(parents=True)
        (slow / "slow_result.json").write_text(
            json.dumps({"action": "force_accept"}), encoding="utf-8"
        )
        return root

    def test_report_counts_only_fast_gate_accepts(self) -> None:
        root = self._write_run(
            "vistr", ["accept_new_best", "force_accept", "reject", "skip_no_patches"]
        )
        result = summarize_run(root)
        self.assertEqual(result["effective_updates"], 1)
        self.assertEqual(result["attempted_fast_steps"], 4)
        self.assertEqual(result["slow_update_actions"], {"force_accept": 1})
        self.assertEqual(result["target_attempts"], 2)
        self.assertEqual(result["timeout_attempts"], 1)

    def test_pair_requires_equal_model_and_step_budget(self) -> None:
        vistr = self._write_run("vistr", ["accept", "reject"])
        docvqa = self._write_run("docvqa", ["accept", "accept_new_best"])
        report = compare(vistr, docvqa)
        self.assertEqual(report["difference"]["effective_updates_docvqa_minus_vistr"], 1)
        self.assertFalse(report["causal_claim"])
        with self.assertRaisesRegex(ValueError, "Expected 16 completed"):
            compare(vistr, docvqa, expected_steps=16)

    def test_report_recovers_baseline_and_step_usage_after_empty_resume(self) -> None:
        root = self._write_run("vistr", ["reject"])
        summary_path = root / "summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["baseline_selection_hard"] = None
        summary["token_summary"] = {"_total": {"calls": 0}}
        summary_path.write_text(json.dumps(summary), encoding="utf-8")
        baseline = root / "selection_eval_baseline"
        baseline.mkdir()
        (baseline / "results.jsonl").write_text(
            json.dumps({"hard": 1}) + "\n", encoding="utf-8"
        )
        history_path = root / "history.json"
        history = json.loads(history_path.read_text(encoding="utf-8"))
        history[0]["tokens"] = {
            "analyst": {"calls": 2, "prompt_tokens": 10, "completion_tokens": 3}
        }
        history_path.write_text(json.dumps(history), encoding="utf-8")

        result = summarize_run(root)

        self.assertEqual(result["baseline_validation_hard"], 1.0)
        self.assertEqual(result["skillopt_usage"]["total_tokens"], 13)

    def test_completed_resume_preserves_existing_summary(self) -> None:
        root = self.root / "resume"
        root.mkdir()
        summary_path = root / "summary.json"
        original = {"baseline_selection_hard": 1, "token_summary": {"calls": 2}}
        summary_path.write_text(json.dumps(original), encoding="utf-8")
        (root / "history.json").write_text(
            json.dumps([{"step": 1, "action": "reject"}]), encoding="utf-8"
        )

        class FakeTrainer:
            def __init__(self, cfg: dict, adapter: object) -> None:
                self.root = Path(cfg["out_root"])

            def train(self) -> dict:
                damaged = {"baseline_selection_hard": None, "token_summary": {}}
                (self.root / "summary.json").write_text(
                    json.dumps(damaged), encoding="utf-8"
                )
                return damaged

        with mock.patch("agent.skillopt.integration.ReflACTTrainer", FakeTrainer):
            _train_preserving_completed_summary({"out_root": str(root)}, object())

        self.assertEqual(json.loads(summary_path.read_text(encoding="utf-8")), original)


if __name__ == "__main__":
    unittest.main()
