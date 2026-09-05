#!/usr/bin/env python3
"""Offline checks for the Fengyuan clean-machine handover assets."""

from __future__ import annotations

import json
import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import yaml


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT.parent / "SkillOpt"))
sys.path.insert(0, str(ROOT))

from skillopt.config import flatten_config, load_config


PREFLIGHT_SPEC = importlib.util.spec_from_file_location(
    "handover_preflight", ROOT / "scripts" / "handover_preflight.py"
)
assert PREFLIGHT_SPEC and PREFLIGHT_SPEC.loader
PREFLIGHT = importlib.util.module_from_spec(PREFLIGHT_SPEC)
PREFLIGHT_SPEC.loader.exec_module(PREFLIGHT)
Checks = PREFLIGHT.Checks
_check_api = PREFLIGHT._check_api


class HandoverAssetTests(unittest.TestCase):
    def test_gpt55_agent_profile_is_medium_and_portable(self) -> None:
        path = ROOT / "configs" / "agent" / "s2_8_gpt55.yaml"
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
        policy = config["models"]["policy"]
        self.assertEqual(policy["id"], "gpt-5.5")
        self.assertEqual(policy["thinking_level"], "medium")
        self.assertEqual(policy["max_tokens"], 65536)
        self.assertEqual(config["providers"]["openai"]["api"], "openai-completions")
        self.assertEqual(config["agent"]["tool_python"], "../../.venv/bin/python")
        self.assertEqual(config["perception"]["visible_devices"], "0")
        self.assertNotIn("/workspace/", path.read_text(encoding="utf-8"))

    def test_gpt55_skillopt_profiles_match_the_fixed_recipe(self) -> None:
        configs = []
        for name in (
            "vistr_comparison_100_gpt55.yaml",
            "docvqa_comparison_100_gpt55.yaml",
        ):
            path = ROOT / "configs" / "skillopt" / name
            structured = load_config(str(path))
            configs.append((structured, flatten_config(structured)))
        for structured, flat in configs:
            self.assertEqual(
                structured["integration"]["agent_config"],
                "../agent/s2_8_gpt55.yaml",
            )
            self.assertEqual(flat["optimizer_model"], "inherit_policy")
            self.assertEqual(flat["target_model"], "inherit_policy")
            self.assertEqual(flat["reasoning_effort"], "medium")
            self.assertEqual(flat["batch_size"], 5)
            self.assertEqual(flat["num_epochs"], 4)
            self.assertEqual(flat["max_completion_tokens"], 16384)

    def test_pi_lock_and_setup_script_are_pinned(self) -> None:
        package = json.loads((
            ROOT / "third_party" / "pi-runtime" / "package.json"
        ).read_text(encoding="utf-8"))
        lock = json.loads((
            ROOT / "third_party" / "pi-runtime" / "package-lock.json"
        ).read_text(encoding="utf-8"))
        self.assertEqual(package["dependencies"]["@earendil-works/pi-coding-agent"], "0.84.0")
        self.assertEqual(
            lock["packages"]["node_modules/@earendil-works/pi-coding-agent"]["version"],
            "0.84.0",
        )
        subprocess.run(
            ["bash", "-n", str(ROOT / "scripts" / "setup_handover_env.sh")],
            check=True,
        )

    def test_api_probe_uses_gpt_reasoning_fields_without_temperature(self) -> None:
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[object()]))]
        )
        create = mock.Mock(return_value=response)
        client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )
        config = SimpleNamespace(
            policy=SimpleNamespace(
                provider="openai", id="gpt-5.5", thinking_level="medium"
            ),
            providers={"openai": SimpleNamespace(
                base_url_env="BASE_URL", api_key_env="API_KEY"
            )},
            env_values={
                "BASE_URL": "https://api.openai.com/v1",
                "API_KEY": "test-key",
            },
        )
        checks = Checks()
        with mock.patch("openai.OpenAI", return_value=client):
            _check_api(checks, config)
        self.assertFalse(checks.failures)
        kwargs = create.call_args.kwargs
        self.assertEqual(kwargs["max_completion_tokens"], 1024)
        self.assertEqual(kwargs["reasoning_effort"], "medium")
        self.assertNotIn("temperature", kwargs)
        self.assertTrue(kwargs["tools"])


if __name__ == "__main__":
    unittest.main()
