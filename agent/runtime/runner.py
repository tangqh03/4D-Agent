"""Configurable Pi-backed rollout runner for the current S2.8 flow."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import stat
import subprocess
import tempfile
import threading
import time
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

from .artifacts import export_and_materialize
from .config import AgentConfig, ModelConfig
from .contracts import AgentItem, AttemptRecord, RolloutRecord
from .pi_events import extract_answer, parse_pi_json
from .tool_bundles import get_tool_bundle


TOOLS_NOTE = """
- index_video: Build a coarse captioned timeline (text only) to discover moments worth inspecting.
- read_video_sequence: View an ordered sequence of frames from a continuous time range.
- read_multiframe: Jointly view selected timestamps for cross-frame comparison.
- read_crop: Zoom into an explicit normalized bounding box (0-1000) in a single frame or video segment.
- semantic_crop: Locate a region from a short English target description and return a context-preserving frame or video crop.
""".strip()


PROMPT = """You are an expert in visual spatial-temporal reasoning. The current working directory contains the source video `video.mp4`; you may freely read and write files in this workspace.

Available capabilities:
- bash: `ffmpeg` and `ffprobe` are installed; `{tool_python}` includes cv2 and numpy for frame extraction, optical flow, frame differencing, and spatial crops.
- read: Directly inspect extracted JPG and PNG images.
{tools_note}

Analyze the video with the available tools, then answer:

Question: {question}
Options: {options}

On a separate final line, output exactly one of the provided options using this format:
<answer>exact option text</answer>"""


class AgentRunner:
    """Reusable runtime that owns configuration, services, and Pi rollouts."""

    def __init__(self, config: AgentConfig):
        self.config = config
        self.bundle = get_tool_bundle(config.agent.tool_bundle)
        self._entered = False
        self._config_tmp: tempfile.TemporaryDirectory[str] | None = None
        self._env: dict[str, str] = {}
        self._service: subprocess.Popen[str] | None = None
        self._service_log = None
        self._runtime_id = time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
        self._write_lock = threading.Lock()

    @classmethod
    def from_yaml(cls, path: str | Path) -> "AgentRunner":
        return cls(AgentConfig.from_yaml(path))

    def __enter__(self) -> "AgentRunner":
        if self._entered:
            return self
        try:
            self.config.artifacts.trajectory_root.mkdir(parents=True, exist_ok=True)
            self._config_tmp = tempfile.TemporaryDirectory(prefix="vistr_pi_config_")
            config_dir = Path(self._config_tmp.name)
            models_path = config_dir / "models.json"
            models_path.write_text(
                json.dumps(self._pi_models_config(), ensure_ascii=False, indent=2),
                encoding="utf-8")
            models_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
            self._env = self.config.child_env()
            self._env["PI_CODING_AGENT_DIR"] = str(config_dir)
            self._inject_observer_env(self._env)
            self._strip_selected_secrets(self._env)
            self._env["VISTR_PERCEPTION_URL"] = self._perception_url()
            self._ensure_perception()
            self._entered = True
            return self
        except Exception:
            self.close()
            raise

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        if self._service is not None and self._service.poll() is None:
            self._service.terminate()
            try:
                self._service.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self._service.kill()
                self._service.wait(timeout=10)
        self._service = None
        if self._service_log is not None:
            self._service_log.close()
            self._service_log = None
        if self._config_tmp is not None:
            self._config_tmp.cleanup()
            self._config_tmp = None
        self._entered = False

    def rollout(self, items: list[AgentItem], *, skill_content: str | None = None,
                run_id: str) -> list[RolloutRecord]:
        if not self._entered:
            raise RuntimeError("AgentRunner must be used as a context manager")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", run_id):
            raise ValueError("run_id must contain only alphanumerics, '.', '_', and '-'")
        ids = [item.id for item in items]
        if len(ids) != len(set(ids)):
            raise ValueError("Agent item IDs must be unique within a rollout")
        safe_ids = [_safe_id(item.id) for item in items]
        if len(safe_ids) != len(set(safe_ids)):
            raise ValueError("Agent item IDs collide after filesystem-safe normalization")
        missing = [str(item.video_path) for item in items if not item.video_path.is_file()]
        if missing:
            raise FileNotFoundError("Video files not found: " + ", ".join(missing))
        for item in items:
            if not item.question.strip() or len(item.options) < 2:
                raise ValueError(f"Agent item {item.id!r} needs a question and at least two options")
            if len(item.options) != len(set(item.options)):
                raise ValueError(f"Agent item {item.id!r} contains duplicate options")
            if item.ground_truth is not None and item.ground_truth not in item.options:
                raise ValueError(f"Agent item {item.id!r} ground_truth is not one of its options")

        skill = (self.config.agent.seed_skill.read_text(encoding="utf-8")
                 if skill_content is None else skill_content)
        run_dir = self.config.artifacts.trajectory_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_manifest(run_dir, skill)
        results_path = run_dir / "results.jsonl"
        existing = self._load_results(results_path)
        pending = [item for item in items if item.id not in existing]

        def run_one(item: AgentItem) -> RolloutRecord:
            record = self._run_item(item, skill, run_id, run_dir)
            with self._write_lock:
                with results_path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
                    stream.flush()
            return record

        fresh: dict[str, RolloutRecord] = {}
        with ThreadPoolExecutor(max_workers=self.config.agent.workers) as pool:
            for record in pool.map(run_one, pending):
                fresh[record.id] = record
        return [existing.get(item.id) or fresh[item.id] for item in items]

    def _run_item(self, item: AgentItem, skill: str, run_id: str,
                  run_dir: Path) -> RolloutRecord:
        started = time.time()
        item_dir = run_dir / _safe_id(item.id)
        item_dir.mkdir(parents=True, exist_ok=True)
        attempts: list[AttemptRecord] = []
        final_parsed = _empty_parse()
        final_answer = None
        final_attempt = None
        final_error = ""

        for retry_index in range(self.config.agent.max_attempts):
            attempt_no = _next_attempt(item_dir)
            attempt_dir = item_dir / f"attempt-{attempt_no}"
            attempt_dir.mkdir()
            user_prompt = PROMPT.format(
                tool_python=self.config.agent.tool_python,
                tools_note=TOOLS_NOTE,
                question=item.question,
                options=" / ".join(item.options),
            )
            process_error = None
            returncode = -1
            stdout = ""
            with tempfile.TemporaryDirectory(prefix="pi_ws_") as workspace:
                shutil.copy2(item.video_path, Path(workspace) / "video.mp4")
                cmd = self._pi_command(attempt_dir, skill, user_prompt,
                                       run_id, item.id, attempt_no)
                try:
                    proc = subprocess.run(cmd, capture_output=True, text=True,
                                          timeout=self.config.agent.timeout_s,
                                          cwd=workspace, env=self._env)
                    returncode = proc.returncode
                    stdout = proc.stdout or ""
                    if returncode != 0:
                        process_error = (f"pi exit {returncode}: "
                                         f"{(proc.stderr or '').strip()[:1000]}")
                except subprocess.TimeoutExpired as exc:
                    stdout = _decode_timeout_output(exc.stdout)
                    process_error = f"pi timeout after {self.config.agent.timeout_s}s"

            parsed = parse_pi_json(stdout)
            answer = extract_answer(parsed["final_text"], parsed["reasoning"], item.options)
            hard = (int(answer == item.ground_truth)
                    if item.ground_truth is not None and not process_error else None)
            soft = float(hard) if hard is not None else None
            attempt_record = export_and_materialize(
                attempt_dir=attempt_dir, pi_binary=self.config.agent.pi_binary,
                env=self._env, item=item, skill_content=skill,
                user_prompt=user_prompt, predicted_answer=answer,
                hard=hard, soft=soft, execution_error=process_error)
            attempts.append(attempt_record)
            if returncode == 0:
                final_parsed = parsed
                final_answer = answer
                final_attempt = attempt_no
                final_error = "" if answer else "No valid answer found"
                break
            final_error = process_error or "Pi failed"
            if retry_index + 1 < self.config.agent.max_attempts:
                time.sleep(self.config.agent.retry_backoff_s * (retry_index + 1))

        selected = next((a for a in attempts if a.number == final_attempt),
                        attempts[-1] if attempts else None)
        hard = (int(final_answer == item.ground_truth)
                if item.ground_truth is not None and final_attempt is not None else None)
        soft = float(hard) if hard is not None else None
        artifact_errors = [error for attempt in attempts for error in attempt.artifact_errors]
        return RolloutRecord(
            id=item.id, question=item.question, task_description=item.question,
            task_type=item.task_type, predicted_answer=final_answer,
            hard=hard, soft=soft, response=final_parsed["final_text"],
            agent_ok=final_attempt is not None,
            fail_reason=final_error, n_turns=len(final_parsed["tool_calls"]),
            usage=final_parsed["usage"], elapsed_s=time.time() - started,
            termination=final_parsed["termination"],
            policy_model=self.config.policy.id,
            observer_model=self.config.observer.id,
            final_attempt=final_attempt, attempts=attempts,
            trajectory_dir=str(item_dir),
            session_jsonl=[] if selected is None else selected.session_jsonl,
            session_html=[] if selected is None else selected.session_html,
            conversation_path=None if selected is None else selected.conversation_path,
            image_paths=[] if selected is None else selected.image_paths,
            artifact_errors=artifact_errors,
            extras={"options": list(item.options), "ground_truth": item.ground_truth,
                    "reasoning": final_parsed["reasoning"],
                    "tool_trace": final_parsed["tool_calls"],
                    "tool_results": final_parsed["tool_results"],
                    "tools_executed": final_parsed["tools_executed"],
                    "tool_errors": final_parsed["tool_errors"],
                    **item.metadata},
        )

    def _pi_command(self, attempt_dir: Path, skill: str, user_prompt: str,
                    run_id: str, item_id: str, attempt_no: int) -> list[str]:
        command = [str(self.config.agent.pi_binary), "-p", "--mode", "json",
                   "--provider", self.config.policy.provider,
                   "--model", self.config.policy.id,
                   "--session-dir", str(attempt_dir),
                   "--name", f"{run_id}:{item_id}:attempt-{attempt_no}",
                   "--no-extensions", "--no-skills", "--no-prompt-templates",
                   "--no-context-files", "--approve",
                   "--tools", ",".join(self.bundle.tools),
                   "--append-system-prompt", skill]
        for extension in self.bundle.extensions:
            command.extend(["-e", str(extension)])
        command.append(user_prompt)
        return command

    def _pi_models_config(self) -> dict:
        used = {self.config.policy.provider, self.config.observer.provider}
        providers = {}
        for provider_name in sorted(used):
            provider = self.config.providers[provider_name]
            models = []
            seen = set()
            for model in (self.config.policy, self.config.observer):
                if model.provider != provider_name or model.id in seen:
                    continue
                seen.add(model.id)
                models.append(_pi_model(model))
            entry = {
                "baseUrl": self.config.env_values[provider.base_url_env],
                "api": provider.api,
                "apiKey": self.config.env_values[provider.api_key_env],
                "models": models,
            }
            if provider.headers_env:
                entry["headers"] = {name: self.config.env_values[env_name]
                                    for name, env_name in provider.headers_env.items()}
            providers[provider_name] = entry
        return {"providers": providers}

    def _inject_observer_env(self, env: dict[str, str]) -> None:
        provider = self.config.providers[self.config.observer.provider]
        env["VISTR_OBSERVER_BASE_URL"] = self.config.env_values[provider.base_url_env]
        env["VISTR_OBSERVER_API_KEY"] = self.config.env_values[provider.api_key_env]
        env["VISTR_OBSERVER_MODEL"] = self.config.observer.id
        env["VISTR_OBSERVER_HEADERS_JSON"] = json.dumps({
            name: self.config.env_values[env_name]
            for name, env_name in provider.headers_env.items()
        })

    def _strip_selected_secrets(self, env: dict[str, str]) -> None:
        """Keep selected credentials out of the model-callable bash environment."""
        for provider in self.config.providers.values():
            env.pop(provider.api_key_env, None)
            for env_name in provider.headers_env.values():
                env.pop(env_name, None)

    def _perception_url(self) -> str:
        return self.config.env_values[self.config.perception.endpoint_env].rstrip("/")

    def _healthy(self) -> bool:
        try:
            with urllib.request.urlopen(self._perception_url() + "/health", timeout=2) as response:
                return response.status == 200
        except Exception:
            return False

    def _ensure_perception(self) -> None:
        if self._healthy():
            return
        parsed = urlparse(self._perception_url())
        if parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.port is None:
            raise ValueError("managed perception endpoint must be a loopback URL with an explicit port")
        log_dir = self.config.artifacts.trajectory_root / "_runtime" / self._runtime_id
        log_dir.mkdir(parents=True, exist_ok=True)
        self._service_log = (log_dir / "perception.log").open("a", encoding="utf-8")
        command = [str(self.config.perception.python), "-u",
                   str(self.config.perception.script), "--port", str(parsed.port)]
        if self.config.perception.eager:
            command.append("--eager")
        env = dict(self._env)
        env.pop("VISTR_OBSERVER_API_KEY", None)
        env.pop("VISTR_OBSERVER_HEADERS_JSON", None)
        env["GDINO_PATH"] = str(self.config.perception.model_path)
        if self.config.perception.visible_devices:
            env["CUDA_VISIBLE_DEVICES"] = self.config.perception.visible_devices
        self._service = subprocess.Popen(command, stdout=self._service_log,
                                         stderr=subprocess.STDOUT, text=True, env=env)
        deadline = time.monotonic() + self.config.perception.startup_timeout_s
        while time.monotonic() < deadline:
            if self._service.poll() is not None:
                raise RuntimeError(f"Perception service exited with {self._service.returncode}; see {log_dir / 'perception.log'}")
            if self._healthy():
                return
            time.sleep(1)
        self.close()
        raise TimeoutError("Perception service did not become healthy before startup timeout")

    def _ensure_manifest(self, run_dir: Path, skill: str) -> None:
        config_json = json.dumps(self.config.public_dict(), sort_keys=True,
                                 separators=(",", ":"))
        expected = {
            "version": 1,
            "config_sha256": hashlib.sha256(config_json.encode()).hexdigest(),
            "skill_sha256": hashlib.sha256(skill.encode()).hexdigest(),
            "policy_model": self.config.policy.id,
            "observer_model": self.config.observer.id,
            "tool_bundle": self.bundle.name,
            "pi_version": _pi_version(self.config.agent.pi_binary, self._env),
        }
        path = run_dir / "manifest.json"
        if path.exists():
            current = json.loads(path.read_text(encoding="utf-8"))
            comparable = {key: current.get(key) for key in expected}
            if comparable != expected:
                raise ValueError(f"run_id already exists with different config or skill: {run_dir.name}")
            return
        path.write_text(json.dumps({**expected, "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")},
                                   ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _load_results(path: Path) -> dict[str, RolloutRecord]:
        records = {}
        if not path.exists():
            return records
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                raw = json.loads(line)
                attempts = [AttemptRecord(**a) for a in raw.pop("attempts")]
                known = {f.name for f in RolloutRecord.__dataclass_fields__.values()}
                extras = {k: raw.pop(k) for k in list(raw) if k not in known}
                raw["attempts"] = attempts
                raw["extras"] = extras
                record = RolloutRecord(**raw)
            except Exception:
                continue
            records[record.id] = record
        return records


def _pi_model(model: ModelConfig) -> dict:
    result = {"id": model.id, "name": model.name,
              "reasoning": model.reasoning, "input": ["text", "image"],
              "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0}}
    if model.context_window != -1:
        result["contextWindow"] = model.context_window
    if model.max_tokens != -1:
        result["maxTokens"] = model.max_tokens
    return result


def _pi_version(binary: Path, env: dict[str, str]) -> str:
    proc = subprocess.run([str(binary), "--version"], capture_output=True,
                          text=True, env=env, timeout=30)
    return proc.stdout.strip() if proc.returncode == 0 else "unknown"


def _safe_id(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    if not safe:
        raise ValueError(f"Invalid item id for artifact path: {value!r}")
    return safe


def _next_attempt(item_dir: Path) -> int:
    numbers = []
    for path in item_dir.glob("attempt-*"):
        try:
            numbers.append(int(path.name.split("-")[-1]))
        except ValueError:
            continue
    return max(numbers, default=0) + 1


def _decode_timeout_output(value) -> str:
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value or ""


def _empty_parse() -> dict:
    return {"reasoning": "", "final_text": "", "usage": {},
            "tool_calls": [], "tool_results": [], "tools_executed": 0,
            "tool_errors": 0,
            "termination": {"stop_reason": "unknown",
                            "provider_error_count": 0, "last_error": None}}
