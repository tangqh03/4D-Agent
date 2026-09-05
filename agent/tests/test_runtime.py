#!/usr/bin/env python
"""Offline tests for the configurable S2.8 runtime."""

from __future__ import annotations

import json
import re
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.datasets import ViSTRAdapter
from agent.runtime import AgentConfig, AgentItem, AgentRunner
from agent.runtime.artifacts import export_and_materialize
from agent.runtime.pi_events import extract_answer
from agent.runtime.runner import PROMPT, TOOLS_NOTE
from agent.runtime.tool_bundles import get_tool_bundle


FAKE_PI = r'''#!/usr/bin/env python3
import base64, json, pathlib, sys

args = sys.argv[1:]
if args == ["--version"]:
    print("0.84.0-test")
    raise SystemExit(0)
if args and args[0] == "--export":
    source = pathlib.Path(args[1])
    target = pathlib.Path(args[2])
    target.write_text("<html><body>" + source.name + "</body></html>")
    raise SystemExit(0)

session_dir = pathlib.Path(args[args.index("--session-dir") + 1])
session = session_dir / "fake-session.jsonl"
entries = [
    {"type":"session","version":3,"id":"fake","timestamp":"now","cwd":"/tmp"},
    {"type":"message","message":{"role":"user","content":[{"type":"text","text":args[-1]}]}},
    {"type":"message","message":{"role":"assistant","content":[
        {"type":"toolCall","id":"call-1","name":"read_video_sequence",
         "arguments":{"path":"video.mp4","start_s":0,"end_s":1}}]}},
    {"type":"message","message":{"role":"toolResult","toolCallId":"call-1",
        "toolName":"read_video_sequence","isError":False,
        "content":[{"type":"text","text":"two frames"},
                   {"type":"image","mimeType":"image/jpeg",
                    "data":base64.b64encode(b"fake-jpeg").decode()}]}},
    {"type":"message","message":{"role":"assistant","stopReason":"stop",
        "content":[{"type":"text","text":"<answer>Yes</answer>"}]}},
]
session.write_text("\n".join(json.dumps(v) for v in entries) + "\n")
events = [
    {"type":"message_end","message":{"role":"assistant","stopReason":"toolUse",
        "content":[{"type":"toolCall","id":"call-1","name":"read_video_sequence",
                    "arguments":{"path":"video.mp4","start_s":0,"end_s":1}}]}},
    {"type":"tool_execution_end","toolCallId":"call-1","toolName":"read_video_sequence",
        "result":{"isError":False,"content":[{"type":"text","text":"two frames"},
        {"type":"image","mimeType":"image/jpeg","data":base64.b64encode(b"fake-jpeg").decode()}]}},
    {"type":"message_end","message":{"role":"assistant","stopReason":"stop",
        "content":[{"type":"text","text":"<answer>Yes</answer>"}]},
        "usage":{"input":10,"output":2}},
]
for event in events:
    print(json.dumps(event))
'''


class RuntimeFixture:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="runtime_test_")
        self.root = Path(self.tmp.name)
        self.dataset = self.root / "dataset"
        self.dataset.mkdir()
        (self.dataset / "video.mp4").write_bytes(b"video")
        (self.dataset / "data.json").write_text(json.dumps([{
            "id": 1, "video": "video.mp4", "direct_prompting": "Did it move?",
            "options": ["Yes", "No"], "answer": "Yes", "task": "Vehicle_Movement",
            "dimension": "Motion_Perception",
        }]), encoding="utf-8")
        self.split = self.root / "split.json"
        self.split.write_text(json.dumps({"Vehicle_Movement": {"dev": [1], "eval": []}}))
        self.skill = self.root / "skill.md"
        self.skill.write_text("# Skill\nInspect frames.", encoding="utf-8")
        self.model_dir = self.root / "gdino"
        self.model_dir.mkdir()
        self.service = self.root / "service.py"
        self.service.write_text("# fake service\n", encoding="utf-8")
        self.pi = self.root / "pi"
        self.pi.write_text(FAKE_PI, encoding="utf-8")
        self.pi.chmod(self.pi.stat().st_mode | stat.S_IXUSR)
        self.dotenv = self.root / ".env.test"
        self.dotenv.write_text(
            "POLICY_URL=http://example.test/v1\n"
            "POLICY_KEY=dotenv-secret\n"
            "PERCEPTION_URL=http://127.0.0.1:7876\n", encoding="utf-8")
        self.config_path = self.root / "agent.yaml"
        self.write_config()

    def write_config(self, extra: dict | None = None):
        data = {
            "version": 1,
            "env_file": str(self.dotenv),
            "providers": {"primary": {"api": "openai-completions",
                "base_url_env": "POLICY_URL", "api_key_env": "POLICY_KEY"}},
            "models": {"policy": {"provider": "primary", "id": "test-vlm",
                "reasoning": True, "context_window": -1, "max_tokens": -1},
                "observer": {"inherit": "policy"}},
            "agent": {"backend": "pi", "tool_bundle": "s2_8_observation",
                "seed_skill": str(self.skill), "timeout_s": 10, "max_attempts": 2,
                "retry_backoff_s": 0, "workers": 2, "pi_binary": str(self.pi),
                "tool_python": sys.executable, "path_prepend": [str(self.root)]},
            "perception": {"mode": "managed", "endpoint_env": "PERCEPTION_URL",
                "python": sys.executable, "script": str(self.service),
                "model_path": str(self.model_dir), "visible_devices": "6",
                "eager": True, "startup_timeout_s": 2},
            "dataset": {"adapter": "vistr", "root": str(self.dataset),
                "split_config": str(self.split)},
            "artifacts": {"trajectory_root": str(self.root / "trajectories")},
        }
        if extra:
            data.update(extra)
        self.config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    def close(self):
        self.tmp.cleanup()


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.fx = RuntimeFixture()

    def tearDown(self):
        self.fx.close()

    def test_loads_strict_config_and_dotenv_wins(self):
        config = AgentConfig.from_yaml(self.fx.config_path)
        env = config.child_env({"POLICY_KEY": "ambient", "PATH": "/bin"})
        self.assertEqual(env["POLICY_KEY"], "dotenv-secret")
        self.assertEqual(config.observer, config.policy)
        self.assertNotIn("dotenv-secret", json.dumps(config.public_dict()))

    def test_unknown_field_fails(self):
        raw = yaml.safe_load(self.fx.config_path.read_text())
        raw["unexpected"] = True
        self.fx.config_path.write_text(yaml.safe_dump(raw))
        with self.assertRaisesRegex(ValueError, "Unknown config fields"):
            AgentConfig.from_yaml(self.fx.config_path)

    def test_minus_one_omits_pi_limits_and_secret(self):
        config = AgentConfig.from_yaml(self.fx.config_path)
        runner = AgentRunner(config)
        rendered = runner._pi_models_config()
        model = rendered["providers"]["primary"]["models"][0]
        self.assertNotIn("contextWindow", model)
        self.assertNotIn("maxTokens", model)
        self.assertEqual(rendered["providers"]["primary"]["apiKey"], "dotenv-secret")

    def test_thinking_level_is_strict_and_requires_reasoning(self):
        raw = yaml.safe_load(self.fx.config_path.read_text())
        raw["models"]["policy"]["reasoning"] = False
        raw["models"]["policy"]["thinking_level"] = "medium"
        self.fx.config_path.write_text(yaml.safe_dump(raw, sort_keys=False))
        with self.assertRaisesRegex(ValueError, "requires reasoning=true"):
            AgentConfig.from_yaml(self.fx.config_path)

        raw["models"]["policy"]["reasoning"] = True
        raw["models"]["policy"]["thinking_level"] = "extreme"
        self.fx.config_path.write_text(yaml.safe_dump(raw, sort_keys=False))
        with self.assertRaisesRegex(ValueError, "thinking_level is invalid"):
            AgentConfig.from_yaml(self.fx.config_path)


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.fx = RuntimeFixture()

    def tearDown(self):
        self.fx.close()

    def test_vistr_adapter_normalizes_item(self):
        config = AgentConfig.from_yaml(self.fx.config_path)
        items = ViSTRAdapter(config.dataset).load(split="dev")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].id, "1")
        self.assertEqual(items[0].ground_truth, "Yes")
        self.assertTrue(items[0].video_path.is_file())


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.fx = RuntimeFixture()

    def tearDown(self):
        self.fx.close()

    def test_active_policy_prompt_is_english(self):
        rendered = PROMPT.format(
            tool_python="/usr/bin/python3",
            tools_note=TOOLS_NOTE,
            question="Did it move?",
            options="Yes / No",
        )
        self.assertIsNone(re.search(r"[\u4e00-\u9fff]", rendered))
        self.assertIn("Question: Did it move?", rendered)
        self.assertIn("<answer>exact option text</answer>", rendered)

    def test_configured_thinking_level_reaches_pi_and_observer(self):
        raw = yaml.safe_load(self.fx.config_path.read_text())
        raw["models"]["policy"]["thinking_level"] = "medium"
        self.fx.config_path.write_text(yaml.safe_dump(raw, sort_keys=False))
        config = AgentConfig.from_yaml(self.fx.config_path)
        runner = AgentRunner(config)
        command = runner._pi_command(
            Path("/tmp/a"), "skill", "prompt", "run", "item", 1
        )
        self.assertEqual(command[command.index("--thinking") + 1], "medium")
        env = {}
        runner._inject_observer_env(env)
        self.assertEqual(env["VISTR_OBSERVER_REASONING_EFFORT"], "medium")

    def test_answer_tag_takes_priority_and_supports_multiline_content(self):
        self.assertEqual(
            extract_answer(
                "The other possibility is No.\n<answer>Yes</answer>",
                "I considered No.",
                ("Yes", "No"),
            ),
            "Yes",
        )
        self.assertEqual(
            extract_answer(
                "<ANSWER>\nCounterclockwise\n</ANSWER>",
                "",
                ("Clockwise", "Counterclockwise"),
            ),
            "Counterclockwise",
        )

    @mock.patch.object(AgentRunner, "_ensure_perception", autospec=True)
    def test_offline_rollout_writes_native_and_reflection_artifacts(self, _ensure):
        config = AgentConfig.from_yaml(self.fx.config_path)
        item = AgentItem(id="item-1", video_path=self.fx.dataset / "video.mp4",
                         question="Did it move?", options=("Yes", "No"),
                         ground_truth="Yes", task_type="Vehicle_Movement")
        with AgentRunner(config) as runner:
            models_json = Path(runner._config_tmp.name) / "models.json"
            self.assertTrue(models_json.is_file())
            self.assertEqual(models_json.stat().st_mode & 0o777, 0o600)
            self.assertNotIn("POLICY_KEY", runner._env)
            records = runner.rollout([item], skill_content="# Candidate\nInspect.",
                                     run_id="offline-run")
        record = records[0]
        self.assertEqual(record.predicted_answer, "Yes")
        self.assertEqual((record.hard, record.soft), (1, 1.0))
        self.assertEqual(record.final_attempt, 1)
        self.assertEqual(len(record.session_jsonl), 1)
        self.assertEqual(len(record.session_html), 1)
        self.assertNotIn("dotenv-secret", json.dumps(record.to_dict()))
        self.assertTrue(Path(record.conversation_path).is_file())
        self.assertEqual(Path(record.image_paths[0]).read_bytes(), b"fake-jpeg")
        conversation = json.loads(Path(record.conversation_path).read_text())
        tool = next(event for event in conversation if event.get("type") == "tool_call")
        self.assertIn("[image] images/", tool["observation"])
        self.assertEqual(tool["obs"], tool["observation"])
        self.assertIn("read_video_sequence", tool["cmd"])
        self.assertIn('"start_s": 0', tool["cmd"])
        self.assertEqual(conversation[-1]["role"], "system")
        self.assertIn("[EVALUATION RESULT]", conversation[-1]["content"])
        self.assertIn("--append-system-prompt", runner._pi_command(
            Path("/tmp/a"), "skill", "prompt", "run", "item", 1))
        self.assertNotIn("submit_answer", Path(record.trajectory_dir,
                         "attempt-1", "target_user_prompt.txt").read_text())

    def test_tool_bundle_is_closed(self):
        bundle = get_tool_bundle("s2_8_observation")
        self.assertEqual(bundle.tools, (
            "read", "bash", "edit", "write", "index_video",
            "read_video_sequence", "read_multiframe", "read_crop", "semantic_crop"))
        with self.assertRaises(ValueError):
            get_tool_bundle("custom")

    @mock.patch.object(AgentRunner, "_ensure_perception", autospec=True)
    def test_invalid_agent_item_fails_before_pi(self, _ensure):
        config = AgentConfig.from_yaml(self.fx.config_path)
        item = AgentItem(id="bad", video_path=self.fx.dataset / "video.mp4",
                         question="Q", options=("Yes", "No"), ground_truth="Maybe")
        with AgentRunner(config) as runner:
            with self.assertRaisesRegex(ValueError, "ground_truth"):
                runner.rollout([item], run_id="bad-item")

    @mock.patch.object(AgentRunner, "_ensure_perception", autospec=True)
    def test_same_manifest_resumes_and_different_skill_is_rejected(self, _ensure):
        config = AgentConfig.from_yaml(self.fx.config_path)
        item = AgentItem(id="resume", video_path=self.fx.dataset / "video.mp4",
                         question="Did it move?", options=("Yes", "No"),
                         ground_truth="Yes")
        with AgentRunner(config) as runner:
            first = runner.rollout([item], skill_content="same", run_id="resume-run")
            second = runner.rollout([item], skill_content="same", run_id="resume-run")
            self.assertEqual(first[0].trajectory_dir, second[0].trajectory_dir)
            self.assertFalse(Path(first[0].trajectory_dir, "attempt-2").exists())
            with self.assertRaisesRegex(ValueError, "different config or skill"):
                runner.rollout([item], skill_content="different", run_id="resume-run")

    def test_html_failure_keeps_conversation_and_answer_artifacts(self):
        attempt = self.fx.root / "attempt-1"
        attempt.mkdir()
        session = attempt / "session.jsonl"
        session.write_text("\n".join([
            json.dumps({"type": "session", "version": 3, "id": "x",
                        "timestamp": "now", "cwd": "/tmp"}),
            json.dumps({"type": "message", "message": {"role": "assistant",
                        "content": [{"type": "text", "text": "<answer>Yes</answer>"}]}}),
        ]) + "\n")
        item = AgentItem(id="x", video_path=self.fx.dataset / "video.mp4",
                         question="Q", options=("Yes", "No"), ground_truth="Yes")
        failed = mock.Mock(returncode=1, stdout="", stderr="export broke")
        with mock.patch("agent.runtime.artifacts.subprocess.run", return_value=failed):
            record = export_and_materialize(
                attempt_dir=attempt, pi_binary=self.fx.pi, env={}, item=item,
                skill_content="skill", user_prompt="prompt", predicted_answer="Yes",
                hard=1, soft=1.0, execution_error=None)
        self.assertTrue(record.artifact_errors)
        self.assertTrue(Path(record.conversation_path).is_file())
        self.assertEqual(record.session_jsonl, [str(session)])


class FakeProcess:
    def __init__(self):
        self.returncode = None
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.fx = RuntimeFixture()

    def tearDown(self):
        self.fx.close()

    def test_healthy_service_is_reused(self):
        runner = AgentRunner(AgentConfig.from_yaml(self.fx.config_path))
        runner._env = runner.config.child_env()
        with mock.patch.object(runner, "_healthy", return_value=True), \
                mock.patch("agent.runtime.runner.subprocess.Popen") as popen:
            runner._ensure_perception()
        popen.assert_not_called()
        self.assertIsNone(runner._service)

    def test_managed_service_starts_eager_and_only_owned_process_stops(self):
        runner = AgentRunner(AgentConfig.from_yaml(self.fx.config_path))
        runner._env = runner.config.child_env()
        process = FakeProcess()
        with mock.patch.object(runner, "_healthy", side_effect=[False, True]), \
                mock.patch("agent.runtime.runner.subprocess.Popen", return_value=process) as popen, \
                mock.patch("agent.runtime.runner.time.sleep"):
            runner._ensure_perception()
        command = popen.call_args.args[0]
        self.assertIn("--eager", command)
        self.assertIn("--port", command)
        self.assertEqual(popen.call_args.kwargs["env"]["GDINO_PATH"], str(self.fx.model_dir))
        self.assertNotIn("VISTR_OBSERVER_API_KEY", popen.call_args.kwargs["env"])
        runner.close()
        self.assertTrue(process.terminated)


if __name__ == "__main__":
    unittest.main()
