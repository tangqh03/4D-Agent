"""Compare one completed ViSTR SkillOpt run with one DocVQA run."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


FAST_ACCEPT_ACTIONS = {"accept", "accept_new_best"}


def _read_json(path: Path) -> Any:
    if not path.is_file():
        raise FileNotFoundError(f"Required SkillOpt artifact not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _read_result_rows(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in root.rglob("results.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _mean_hard(path: Path) -> float | None:
    if not path.is_file():
        return None
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("hard") is not None:
            rows.append(float(row["hard"]))
    return sum(rows) / len(rows) if rows else None


def _step_usage(history: list[dict[str, Any]]) -> dict[str, int]:
    usage = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}
    for row in history:
        tokens = row.get("tokens", {})
        if not isinstance(tokens, dict):
            continue
        for role_usage in tokens.values():
            if not isinstance(role_usage, dict):
                continue
            for key in usage:
                usage[key] += int(role_usage.get(key, 0) or 0)
    usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
    return usage


def summarize_run(root: Path) -> dict[str, Any]:
    summary = _read_json(root / "summary.json")
    history = _read_json(root / "history.json")
    if not isinstance(history, list):
        raise ValueError(f"Expected history.json to contain a list: {root}")
    accepts = sum(row.get("action") in FAST_ACCEPT_ACTIONS for row in history)
    result_rows = _read_result_rows(root)
    slow_actions: Counter[str] = Counter()
    for path in root.glob("slow_update/epoch_*/slow_result.json"):
        value = _read_json(path)
        slow_actions[str(value.get("action") or "unknown")] += 1
    total_steps = len(history)
    baseline_validation = summary.get("baseline_selection_hard")
    if baseline_validation is None:
        baseline_validation = _mean_hard(
            root / "selection_eval_baseline" / "results.jsonl"
        )
    best_validation = summary.get("best_selection_hard")
    if best_validation is None and history:
        best_validation = history[-1].get("best_score")
    summary_usage = summary.get("token_summary", {}).get("_total", {})
    step_usage = _step_usage(history)
    if int(summary_usage.get("calls", 0) or 0) == 0 and step_usage["calls"]:
        summary_usage = step_usage
    return {
        "run_root": str(root.resolve()),
        "environment": summary.get("config", {}).get("env"),
        "model": summary.get("config", {}).get("target_model"),
        "attempted_fast_steps": total_steps,
        "effective_updates": accepts,
        "effective_update_rate": accepts / total_steps if total_steps else 0.0,
        "non_empty_patch_steps": sum(int(row.get("n_patches", 0)) > 0 for row in history),
        "candidate_steps": sum(
            bool(row.get("candidate_hash")) and int(row.get("n_edits_ranked", 0)) > 0
            for row in history
        ),
        "reject_steps": sum(row.get("action") == "reject" for row in history),
        "skip_steps": sum(str(row.get("action", "")).startswith("skip") for row in history),
        "edit_budget_schedule": [row.get("edit_budget") for row in history],
        "baseline_validation_hard": baseline_validation,
        "best_validation_hard": best_validation,
        "baseline_test_hard": summary.get("baseline_test_hard"),
        "best_test_hard": summary.get("test_hard"),
        "test_delta_hard": summary.get("test_delta_hard"),
        "slow_update_actions": dict(sorted(slow_actions.items())),
        "target_rollouts": len(result_rows),
        "target_failures": sum(not bool(row.get("agent_ok", True)) for row in result_rows),
        "target_attempts": sum(int(row.get("attempts", 1)) for row in result_rows),
        "timeout_attempts": sum(int(row.get("timeout_attempts", 0)) for row in result_rows),
        "skillopt_usage": summary_usage,
        "step_usage": step_usage,
    }


def compare(
    vistr_root: Path,
    docvqa_root: Path,
    *,
    expected_steps: int | None = None,
) -> dict[str, Any]:
    vistr = summarize_run(vistr_root)
    docvqa = summarize_run(docvqa_root)
    if vistr["model"] != docvqa["model"]:
        raise ValueError(
            f"Target models differ: ViSTR={vistr['model']!r}, DocVQA={docvqa['model']!r}"
        )
    if vistr["attempted_fast_steps"] != docvqa["attempted_fast_steps"]:
        raise ValueError("Runs do not have the same Fast Update Step budget")
    if expected_steps is not None and vistr["attempted_fast_steps"] != expected_steps:
        raise ValueError(
            f"Expected {expected_steps} completed Fast Update Steps per run, got "
            f"{vistr['attempted_fast_steps']}"
        )
    return {
        "experiment": "skillopt_vistr_vs_docvqa_single_seed_pilot",
        "primary_metric": "effective_updates",
        "causal_claim": False,
        "expected_fast_steps": expected_steps,
        "complete": expected_steps is None or vistr["attempted_fast_steps"] == expected_steps,
        "interpretation": (
            "System-level correlation pilot; an update-count difference does not by itself "
            "prove an Outcome False Positive mechanism."
        ),
        "vistr": vistr,
        "docvqa": docvqa,
        "difference": {
            "effective_updates_docvqa_minus_vistr": (
                docvqa["effective_updates"] - vistr["effective_updates"]
            ),
            "effective_update_rate_docvqa_minus_vistr": (
                docvqa["effective_update_rate"] - vistr["effective_update_rate"]
            ),
        },
    }


def _markdown(report: dict[str, Any]) -> str:
    rows = []
    for label, key in (("ViSTR", "vistr"), ("DocVQA", "docvqa")):
        value = report[key]
        rows.append(
            f"| {label} | {value['effective_updates']}/{value['attempted_fast_steps']} "
            f"| {value['effective_update_rate']:.1%} "
            f"| {value['non_empty_patch_steps']} | {value['candidate_steps']} "
            f"| {value['baseline_validation_hard']} → {value['best_validation_hard']} "
            f"| {value['baseline_test_hard']} → {value['best_test_hard']} "
            f"| {value['target_rollouts']} |"
        )
    return "\n".join([
        "# SkillOpt ViSTR vs DocVQA pilot",
        "",
        "| Benchmark | Effective updates | Rate | Patch steps | Candidate steps | Validation | Test | Target rollouts |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
        *rows,
        "",
        f"DocVQA − ViSTR effective updates: "
        f"{report['difference']['effective_updates_docvqa_minus_vistr']}",
        "",
        "> This is a single-seed system-level correlation pilot. It does not "
        "establish that Outcome False Positives caused the observed difference.",
        "",
    ])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vistr", required=True)
    parser.add_argument("--docvqa", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument(
        "--expected-steps",
        type=int,
        default=None,
        help="Require this many completed Fast Update Steps in both histories",
    )
    args = parser.parse_args()
    report = compare(
        Path(args.vistr),
        Path(args.docvqa),
        expected_steps=args.expected_steps,
    )
    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "comparison.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / "comparison.md").write_text(_markdown(report), encoding="utf-8")
    print(_markdown(report))


if __name__ == "__main__":
    main()
