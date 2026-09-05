#!/usr/bin/env python3
"""Validate a clean-machine GPT-5.5 handover before paid SkillOpt runs."""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib
import io
import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SKILLOPT_COMMIT = "db46cd9ae7ce12f1dbd73c945185816aa738751d"
VISTR_DATA_SHA256 = "9b0b1d1bdc074c464c5bb9cb64f7c9676ad881fc2f9be469a6ec6c46518b1a7a"


class Checks:
    def __init__(self) -> None:
        self.failures: list[str] = []

    def ok(self, name: str, detail: str) -> None:
        print(f"[PASS] {name}: {detail}")

    def fail(self, name: str, detail: str) -> None:
        self.failures.append(name)
        print(f"[FAIL] {name}: {detail}")

    def require(self, name: str, condition: bool, detail: str) -> None:
        (self.ok if condition else self.fail)(name, detail)


def _run(command: list[str], *, env: dict[str, str] | None = None) -> str:
    return subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    ).stdout.strip()


def _check_python(checks: Checks) -> None:
    checks.require(
        "python",
        sys.version_info[:2] == (3, 11),
        f"running {sys.version.split()[0]}; expected Python 3.11",
    )
    modules = (
        "dotenv", "flask", "huggingface_hub", "numpy", "openai",
        "cv2", "PIL", "pyarrow", "torch", "transformers", "yaml",
    )
    missing = []
    for name in modules:
        try:
            importlib.import_module(name)
        except ImportError:
            missing.append(name)
    checks.require(
        "python packages",
        not missing,
        "all required imports available" if not missing else "missing: " + ", ".join(missing),
    )


def _check_skillopt(checks: Checks, root: Path) -> None:
    try:
        commit = _run(["git", "-C", str(root), "rev-parse", "HEAD"])
        dirty = _run([
            "git", "-C", str(root), "status", "--porcelain", "--untracked-files=no",
        ])
    except (OSError, subprocess.SubprocessError) as exc:
        checks.fail("SkillOpt checkout", type(exc).__name__)
        return
    checks.require(
        "SkillOpt commit", commit == SKILLOPT_COMMIT, f"found {commit}",
    )
    checks.require(
        "SkillOpt clean tree", not dirty, "clean" if not dirty else "tracked changes present",
    )
    try:
        importlib.import_module("skillopt")
    except ImportError:
        checks.fail("SkillOpt import", "run scripts/setup_handover_env.sh")
    else:
        checks.ok("SkillOpt import", str(root))


def _check_commands(checks: Checks, config: object) -> None:
    child_env = config.child_env()
    for name in ("ffmpeg", "ffprobe"):
        try:
            output = _run([name, "-version"], env=child_env).splitlines()[0]
        except (OSError, subprocess.SubprocessError) as exc:
            checks.fail(name, type(exc).__name__)
        else:
            checks.ok(name, output)
    try:
        encoders = _run(["ffmpeg", "-hide_banner", "-encoders"], env=child_env)
    except (OSError, subprocess.SubprocessError) as exc:
        checks.fail("libx264", type(exc).__name__)
    else:
        checks.require("libx264", "libx264" in encoders, "encoder available")
    try:
        pi_version = _run([str(config.agent.pi_binary), "--version"], env=child_env)
    except (OSError, subprocess.SubprocessError) as exc:
        checks.fail("Pi runtime", type(exc).__name__)
    else:
        checks.require("Pi runtime", "0.84.0" in pi_version, pi_version)


def _check_gpu(checks: Checks) -> None:
    try:
        import torch

        available = torch.cuda.is_available()
        detail = torch.cuda.get_device_name(0) if available else "torch.cuda is unavailable"
    except Exception as exc:  # noqa: BLE001 - preflight reports dependency failures
        checks.fail("NVIDIA CUDA", type(exc).__name__)
        return
    checks.require("NVIDIA CUDA", available, detail)


def _check_data(checks: Checks, config: object, comparison_config: Path) -> None:
    vistr_file = config.dataset.root / "data.json"
    try:
        raw_data = vistr_file.read_bytes()
        rows = json.loads(raw_data)
        missing_videos = [
            str(row["video"]) for row in rows
            if not (config.dataset.root / str(row["video"])).is_file()
        ]
    except (OSError, ValueError, KeyError) as exc:
        checks.fail("ViSTR dataset", type(exc).__name__)
    else:
        checks.require(
            "ViSTR dataset",
            len(rows) == 670
            and not missing_videos
            and hashlib.sha256(raw_data).hexdigest() == VISTR_DATA_SHA256,
            f"rows={len(rows)} missing_videos={len(missing_videos)}",
        )

    raw = yaml.safe_load(comparison_config.read_text(encoding="utf-8"))
    parquet_dir = (comparison_config.parent / raw["docvqa_parquet_dir"]).resolve()
    shards = sorted(parquet_dir.glob("validation-*.parquet"))
    try:
        import pyarrow.parquet as pq

        row_count = sum(pq.ParquetFile(path).metadata.num_rows for path in shards)
    except Exception as exc:  # noqa: BLE001 - preflight reports malformed data
        checks.fail("DocVQA validation", type(exc).__name__)
    else:
        checks.require(
            "DocVQA validation",
            len(shards) == 6 and row_count == 5349,
            f"shards={len(shards)} rows={row_count}",
        )

    model_dir = config.perception.model_path
    required = ("config.json", "preprocessor_config.json", "tokenizer.json")
    has_weights = any((model_dir / name).is_file() for name in (
        "model.safetensors", "pytorch_model.bin",
    ))
    checks.require(
        "GroundingDINO model",
        has_weights and all((model_dir / name).is_file() for name in required),
        str(model_dir),
    )


def _check_api(checks: Checks, config: object) -> None:
    from openai import OpenAI
    from PIL import Image

    provider = config.providers[config.policy.provider]
    base_url = config.env_values[provider.base_url_env]
    api_key = config.env_values[provider.api_key_env]
    if urlparse(base_url).hostname != "api.openai.com":
        checks.fail("OpenAI API", f"unexpected Base URL host: {urlparse(base_url).hostname}")
        return
    client = OpenAI(base_url=base_url.rstrip("/"), api_key=api_key, timeout=120)
    image_buffer = io.BytesIO()
    Image.new("RGB", (32, 32), "white").save(image_buffer, format="PNG")
    image_b64 = base64.b64encode(image_buffer.getvalue()).decode()
    try:
        response = client.chat.completions.create(
            model=config.policy.id,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": "Call report_color for this white square."},
                    {"type": "image_url", "image_url": {"url": (
                        "data:image/png;base64," + image_b64
                    )}},
                ],
            }],
            tools=[{
                "type": "function",
                "function": {
                    "name": "report_color",
                    "description": "Report the dominant image color.",
                    "parameters": {
                        "type": "object",
                        "properties": {"color": {"type": "string"}},
                        "required": ["color"],
                        "additionalProperties": False,
                    },
                    "strict": True,
                },
            }],
            tool_choice={"type": "function", "function": {"name": "report_color"}},
            max_completion_tokens=1024,
            reasoning_effort=config.policy.thinking_level or "medium",
        )
        tool_calls = response.choices[0].message.tool_calls or []
    except Exception as exc:  # noqa: BLE001 - never print request headers or the key
        status = getattr(exc, "status_code", None)
        detail = type(exc).__name__ + (f" HTTP {status}" if status else "")
        checks.fail("OpenAI multimodal tool call", detail)
    else:
        checks.require(
            "OpenAI multimodal tool call",
            bool(tool_calls),
            f"model={config.policy.id} tool_calls={len(tool_calls)}",
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--agent-config",
        default=str(ROOT / "configs" / "agent" / "s2_8_gpt55.yaml"),
    )
    parser.add_argument(
        "--comparison-config",
        default=str(ROOT / "configs" / "skillopt" / "comparison_100.yaml"),
    )
    parser.add_argument(
        "--api",
        action="store_true",
        help="Make one paid GPT-5.5 image+function-call request",
    )
    args = parser.parse_args()

    checks = Checks()
    _check_python(checks)
    from agent.runtime import AgentConfig

    try:
        config = AgentConfig.from_yaml(args.agent_config)
    except Exception as exc:  # noqa: BLE001 - show type without leaking dotenv values
        checks.fail("agent config", f"{type(exc).__name__}: {exc}")
        raise SystemExit(1) from None
    checks.ok(
        "agent config",
        f"{config.policy.id} reasoning={config.policy.thinking_level or 'off'}",
    )
    provider = config.providers[config.policy.provider]
    base_url = config.env_values[provider.base_url_env]
    api_key = config.env_values[provider.api_key_env]
    checks.require(
        "GPT experiment model",
        config.policy.id == "gpt-5.5" and config.policy.thinking_level == "medium",
        f"model={config.policy.id} reasoning={config.policy.thinking_level or 'off'}",
    )
    checks.require(
        "OpenAI endpoint",
        urlparse(base_url).hostname == "api.openai.com",
        urlparse(base_url).hostname or "missing host",
    )
    checks.require(
        "OpenAI credential",
        bool(api_key) and api_key not in {"replace-me", "<fengyuan-openai-api-key>"},
        "non-placeholder value loaded from .env.gpt55",
    )
    checks.require(
        "configured Python",
        config.agent.tool_python.resolve() == Path(sys.executable).resolve()
        and config.perception.python.resolve() == Path(sys.executable).resolve(),
        str(Path(sys.executable).resolve()),
    )
    _check_skillopt(checks, ROOT.parent / "SkillOpt")
    _check_commands(checks, config)
    _check_gpu(checks)
    _check_data(checks, config, Path(args.comparison_config).resolve())
    if args.api:
        _check_api(checks, config)

    if checks.failures:
        print("\nPreflight failed: " + ", ".join(checks.failures))
        raise SystemExit(1)
    print("\nPreflight passed" + (" (including paid API probe)" if args.api else ""))


if __name__ == "__main__":
    main()
