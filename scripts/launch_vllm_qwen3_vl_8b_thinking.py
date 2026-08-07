#!/usr/bin/env python3
"""Launch a local OpenAI-compatible vLLM server for Qwen3-VL-8B-Thinking.

The server settings live in configs/vllm_qwen3_vl_8b_thinking.json.
Set VLLM_PYTHON when vLLM is installed in a different Python environment.

Examples:
    python scripts/launch_vllm_qwen3_vl_8b_thinking.py --dry-run
    python scripts/launch_vllm_qwen3_vl_8b_thinking.py
    python scripts/launch_vllm_qwen3_vl_8b_thinking.py --print-client-env
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_DIR / "configs" / "vllm_qwen3_vl_8b_thinking.json"


def load_config(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        config = json.load(f)

    required = [
        "model",
        "served_model_name",
        "host",
        "port",
        "cuda_visible_devices",
        "tensor_parallel_size",
        "max_model_len",
        "max_num_seqs",
        "dtype",
    ]
    missing = [key for key in required if key not in config]
    if missing:
        raise ValueError(f"Missing config fields: {', '.join(missing)}")
    return config


def build_command(config: dict[str, Any], python_executable: str) -> list[str]:
    qwen = config.get("qwen3_vl", {})
    command = [
        python_executable,
        "-m",
        "vllm.entrypoints.openai.api_server",
        "--model",
        str(config["model"]),
        "--served-model-name",
        str(config["served_model_name"]),
        "--tensor-parallel-size",
        str(config["tensor_parallel_size"]),
        "--max-model-len",
        str(config["max_model_len"]),
        "--max-num-seqs",
        str(config["max_num_seqs"]),
        "--dtype",
        str(config["dtype"]),
        "--host",
        str(config["host"]),
        "--port",
        str(config["port"]),
        "--gpu-memory-utilization",
        str(config.get("gpu_memory_utilization", 0.9)),
    ]

    if config.get("trust_remote_code", True):
        command.append("--trust-remote-code")
    if config.get("enable_prefix_caching", True):
        command.append("--enable-prefix-caching")

    flag_map = {
        "mm_encoder_tp_mode": "--mm-encoder-tp-mode",
        "async_scheduling": "--async-scheduling",
        "distributed_executor_backend": "--distributed-executor-backend",
        "mm_processor_cache_gb": "--mm-processor-cache-gb",
        "attention_backend": "--attention-backend",
        "reasoning_parser": "--reasoning-parser",
    }
    for key, flag in flag_map.items():
        value = qwen.get(key)
        if value is None or value is False:
            continue
        if value is True:
            command.append(flag)
        else:
            command.extend([flag, str(value)])
    return command


def print_client_env(config: dict[str, Any]) -> None:
    client = config["client"]
    print(f"export VISTR_LLM_BASE_URL={shlex.quote(client['base_url'])}")
    print(f"export VISTR_LLM_MODEL={shlex.quote(client['model'])}")
    print(f"export VISTR_LLM_API_KEYS={shlex.quote(client['api_key'])}")
    print(f"export VISTR_PI_PROVIDER={shlex.quote(client['pi_provider'])}")
    print(f"export VISTR_PI_MODEL={shlex.quote(client['model'])}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help="vLLM JSON config path",
    )
    parser.add_argument(
        "--python",
        default=os.environ.get("VLLM_PYTHON", sys.executable),
        help="Python interpreter containing vLLM; defaults to VLLM_PYTHON or current Python",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the launch command without starting vLLM",
    )
    parser.add_argument(
        "--print-client-env",
        action="store_true",
        help="print environment exports for the baseline and pi clients",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    command = build_command(config, args.python)

    if args.print_client_env:
        print_client_env(config)
        return 0

    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = str(config["cuda_visible_devices"])

    print(f"Model: {config['model']}", flush=True)
    print(f"Served name: {config['served_model_name']}", flush=True)
    print(f"Endpoint: {config['client']['base_url']}", flush=True)
    print(f"CUDA_VISIBLE_DEVICES={env['CUDA_VISIBLE_DEVICES']}", flush=True)
    print(f"Launch command: {shlex.join(command)}", flush=True)

    if args.dry_run:
        return 0

    try:
        return subprocess.run(command, env=env).returncode
    except FileNotFoundError as exc:
        print(
            f"Cannot start vLLM with {args.python!r}. "
            "Install vLLM there or set VLLM_PYTHON to the correct interpreter.",
            file=sys.stderr,
        )
        print(f"Details: {exc}", file=sys.stderr)
        return 127


if __name__ == "__main__":
    raise SystemExit(main())
