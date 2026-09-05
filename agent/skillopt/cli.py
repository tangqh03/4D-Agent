"""Bootstrap the pinned external SkillOpt package and run configured training."""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import yaml


SMOKE_OVERRIDES = (
    "train.num_epochs=1",
    "train.batch_size=2",
    "gradient.minibatch_size=2",
    "gradient.merge_batch_size=2",
    "gradient.analyst_workers=2",
    "optimizer.use_slow_update=false",
    "optimizer.use_meta_skill=false",
    "evaluation.sel_env_num=1",
    "evaluation.eval_test=false",
    "env.limit=2",
)


def _path(base: Path, value: object, name: str) -> Path:
    if not value:
        raise ValueError(f"Missing {name}")
    path = Path(str(value)).expanduser()
    return (base / path).resolve() if not path.is_absolute() else path.resolve()


def _bootstrap(config_path: Path) -> tuple[Path, str]:
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    integration = raw.get("integration")
    if not isinstance(integration, dict):
        raise ValueError("SkillOpt config requires an integration mapping")
    root = _path(config_path.parent, integration.get("skillopt_root"),
                 "integration.skillopt_root")
    expected = str(integration.get("expected_commit") or "").strip()
    if not expected:
        raise ValueError("Missing integration.expected_commit")
    if not (root / "skillopt" / "engine" / "trainer.py").is_file():
        raise FileNotFoundError(f"SkillOpt source tree not found: {root}")

    head = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    if head != expected:
        raise RuntimeError(f"SkillOpt commit mismatch: expected {expected}, got {head}")
    dirty = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    if dirty:
        raise RuntimeError("SkillOpt has tracked working-tree changes; refusing a non-reproducible run")
    sys.path.insert(0, str(root))
    return root, head


def main() -> None:
    parser = argparse.ArgumentParser(description="Train a configured agent Skill with SkillOpt")
    parser.add_argument("--config", required=True, help="ViSTR or DocVQA SkillOpt YAML")
    parser.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                        help="Override a structured SkillOpt config value")
    parser.add_argument("--smoke", action="store_true",
                        help="Run one paid two-item training step with one-item validation")
    args = parser.parse_args()

    config_path = Path(args.config).expanduser().resolve()
    if not config_path.is_file():
        raise FileNotFoundError(f"SkillOpt config not found: {config_path}")
    print(f"[{datetime.now().isoformat(timespec='seconds')}] validating SkillOpt source")
    _, commit = _bootstrap(config_path)

    from .integration import run_training

    overrides = [*(SMOKE_OVERRIDES if args.smoke else ()), *args.set]
    print(f"[{datetime.now().isoformat(timespec='seconds')}] starting SkillOpt at {commit[:12]}")
    run_training(config_path, overrides=overrides, smoke=args.smoke)
