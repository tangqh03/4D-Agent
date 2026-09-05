"""Prepare the fixed 100-item ViSTR/DocVQA comparison datasets."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from collections import Counter
from pathlib import Path
from typing import Any, Callable

import yaml


def _resolve(base: Path, value: object, name: str) -> Path:
    if not value:
        raise ValueError(f"Missing {name}")
    path = Path(str(value)).expanduser()
    return (base / path).resolve() if not path.is_absolute() else path.resolve()


def _sha256_files(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _sample_sorted(
    items: list[dict[str, Any]],
    *,
    count: int,
    seed: int,
    key: Callable[[dict[str, Any]], int],
) -> list[dict[str, Any]]:
    if len(items) < count:
        raise ValueError(f"Cannot sample {count} items from a pool of {len(items)}")
    ordered = sorted(items, key=key)
    sampled = random.Random(seed).sample(ordered, count)
    return sorted(sampled, key=key)


def _split_items(
    items: list[dict[str, Any]], seed: int
) -> dict[str, list[dict[str, Any]]]:
    if len(items) != 100:
        raise ValueError(f"Comparison pool must contain exactly 100 items, got {len(items)}")
    shuffled = list(items)
    random.Random(seed).shuffle(shuffled)
    return {
        "train": shuffled[:20],
        "val": shuffled[20:30],
        "test": shuffled[30:],
    }


def _load_docvqa_candidates(manifest_dir: Path) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for split in ("train", "val", "test"):
        path = manifest_dir / split / "items.json"
        rows = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            raise ValueError(f"Expected a JSON array in {path}")
        candidates.extend(rows)
    ids = [str(row["questionId"]) for row in candidates]
    images = [str(row["image_path"]) for row in candidates]
    if len(candidates) != 534 or len(ids) != len(set(ids)):
        raise ValueError("Expected the SkillOpt DocVQA manifest to contain 534 unique IDs")
    if len(images) != len(set(images)):
        raise ValueError("SkillOpt DocVQA comparison pool must contain unique images")
    return candidates


def _materialize_docvqa(
    selected: list[dict[str, Any]], parquet_dir: Path, output_dir: Path, split_seed: int
) -> dict[str, list[str]]:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise ImportError("DocVQA materialization requires pyarrow") from exc

    selected_ids = {str(row["questionId"]) for row in selected}
    source_by_id = {str(row["questionId"]): row for row in selected}
    columns = [
        "questionId", "question", "image", "docId", "ucsf_document_id",
        "ucsf_document_page_no", "answers", "data_split",
    ]
    materialized: dict[str, dict[str, Any]] = {}
    parquet_files = sorted(parquet_dir.glob("validation-*.parquet"))
    if not parquet_files:
        raise FileNotFoundError(f"No DocVQA validation parquet files in {parquet_dir}")
    for path in parquet_files:
        table = pq.read_table(
            path,
            columns=columns,
            filters=[("questionId", "in", sorted(selected_ids))],
        )
        for row in table.to_pylist():
            question_id = str(row["questionId"])
            if question_id in selected_ids:
                materialized[question_id] = row
    missing = sorted(selected_ids - set(materialized), key=int)
    if missing:
        raise ValueError(f"Selected DocVQA IDs missing from local validation data: {missing[:10]}")

    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    normalized: list[dict[str, Any]] = []
    for selected_row in selected:
        question_id = str(selected_row["questionId"])
        row = materialized[question_id]
        answers = [str(value) for value in (row.get("answers") or []) if str(value).strip()]
        if not answers:
            raise ValueError(f"DocVQA question {question_id} has no answer")
        image = row.get("image") or {}
        image_bytes = image.get("bytes") if isinstance(image, dict) else None
        if not image_bytes:
            raise ValueError(f"DocVQA question {question_id} has no image bytes")
        source_name = str(image.get("path") or "image.png")
        suffix = Path(source_name).suffix.lower() or ".png"
        image_path = (images_dir / f"q{question_id}_d{row['docId']}{suffix}").resolve()
        image_path.write_bytes(image_bytes)
        source = source_by_id[question_id]
        normalized.append({
            "questionId": question_id,
            "question": str(row["question"]),
            "answer": repr(answers),
            "image_path": str(image_path),
            "topic": str(source.get("topic") or "docvqa"),
            "docId": str(row["docId"]),
            "ucsf_document_id": str(row.get("ucsf_document_id") or ""),
            "ucsf_document_page_no": str(row.get("ucsf_document_page_no") or ""),
            "source_split": str(row.get("data_split") or "validation"),
        })

    splits = _split_items(normalized, split_seed)
    fieldnames = list(normalized[0])
    split_ids: dict[str, list[str]] = {}
    for name, rows in splits.items():
        split_dir = output_dir / "splits" / name
        split_dir.mkdir(parents=True, exist_ok=True)
        with (split_dir / "items.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        split_ids[name] = [str(row["questionId"]) for row in rows]
    return split_ids


def prepare(config_path: Path) -> dict[str, Any]:
    from .cli import _bootstrap

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if raw.get("version") != 1:
        raise ValueError("comparison config version must be 1")
    if raw.get("sample_count") != 100 or raw.get("split_ratio") != "2:1:7":
        raise ValueError("comparison requires sample_count=100 and split_ratio=2:1:7")
    sample_seed = int(raw.get("sample_seed", 0))
    split_seed = int(raw.get("split_seed", 0))
    if sample_seed != 43 or split_seed != 43:
        raise ValueError("comparison sampling and split seeds must both be 43")
    base = config_path.parent
    _, skillopt_commit = _bootstrap(config_path)
    output_dir = _resolve(base, raw.get("output_dir"), "output_dir")
    output_dir.mkdir(parents=True, exist_ok=True)

    vistr_path = _resolve(base, raw.get("vistr_data"), "vistr_data")
    vistr_rows = json.loads(vistr_path.read_text(encoding="utf-8"))
    vistr_selected = _sample_sorted(
        vistr_rows, count=100, seed=sample_seed, key=lambda row: int(row["id"])
    )
    if any(len(row.get("options", [])) != 2 for row in vistr_rows):
        raise ValueError("This comparison expects every ViSTR item to be binary choice")
    all_tasks = {str(row["task"]) for row in vistr_rows}
    selected_tasks = {str(row["task"]) for row in vistr_selected}
    if selected_tasks != all_tasks:
        missing = sorted(all_tasks - selected_tasks)
        raise ValueError(f"ViSTR seed {sample_seed} does not cover every task: {missing}")
    vistr_ids = [str(row["id"]) for row in vistr_selected]
    (output_dir / "vistr_ids.json").write_text(
        json.dumps(vistr_ids, indent=2) + "\n", encoding="utf-8"
    )
    vistr_splits = _split_items(vistr_selected, split_seed)

    doc_manifest_dir = _resolve(
        base, raw.get("docvqa_manifest_dir"), "docvqa_manifest_dir"
    )
    doc_candidates = _load_docvqa_candidates(doc_manifest_dir)
    doc_selected = _sample_sorted(
        doc_candidates,
        count=100,
        seed=sample_seed,
        key=lambda row: int(row["questionId"]),
    )
    parquet_dir = _resolve(base, raw.get("docvqa_parquet_dir"), "docvqa_parquet_dir")
    doc_output = output_dir / "docvqa"
    doc_split_ids = _materialize_docvqa(
        doc_selected, parquet_dir, doc_output, split_seed
    )

    source_manifest_files = [doc_manifest_dir / "split_manifest.json"] + [
        doc_manifest_dir / split / "items.json" for split in ("train", "val", "test")
    ]
    manifest = {
        "version": 1,
        "sample_count": 100,
        "sample_seed": sample_seed,
        "split_seed": split_seed,
        "split_ratio": "2:1:7",
        "selection_rule": "sort numeric ID, random.sample, sort numeric ID, shuffle for split",
        "skillopt_commit": skillopt_commit,
        "counts": {"train": 20, "val": 10, "test": 70},
        "vistr": {
            "source": str(vistr_path),
            "source_sha256": hashlib.sha256(vistr_path.read_bytes()).hexdigest(),
            "ids": vistr_ids,
            "splits": {
                name: [str(row["id"]) for row in rows]
                for name, rows in vistr_splits.items()
            },
            "task_distribution": dict(sorted(Counter(
                str(row["task"]) for row in vistr_selected
            ).items())),
            "option_count_distribution": {"2": 100},
        },
        "docvqa": {
            "source": str(parquet_dir),
            "manifest_source": str(doc_manifest_dir),
            "manifest_sha256": _sha256_files(source_manifest_files),
            "ids": [str(row["questionId"]) for row in doc_selected],
            "splits": doc_split_ids,
            "unique_images": 100,
            "topic_distribution": dict(sorted(Counter(
                str(row.get("topic") or "docvqa") for row in doc_selected
            ).items())),
        },
    }
    manifest_path = output_dir / "comparison_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Prepared ViSTR and DocVQA comparison data at {output_dir}")
    print("ViSTR: 100 items, 15 tasks; DocVQA: 100 items, 100 unique images")
    print("Splits: train=20 val=10 test=70")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    prepare(Path(args.config).expanduser().resolve())


if __name__ == "__main__":
    main()
