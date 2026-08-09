---
date: 2026-08-07
experiment: qwen3-vl-8b-thinking via local vLLM — baseline vs pi
model: /data/Qwen3-VL-8B-Thinking/
endpoint: http://127.0.0.1:8001/v1
split: dev
samples: 403
---

# Qwen3-VL-8B-Thinking vLLM baseline/pi evaluation

## Setup

- vLLM: GPU 4–7, tensor parallel size 4, `max-model-len=61440`, port 8001.
- Both harnesses used the same served model `qwen3-vl-8b-thinking`.
- Baseline: `agent/eval_baseline.py`, 8 sampled frames, `max_tokens=4096`.
- pi: `agent/eval_pi.py`, pi v0.84.0, 8 sampled frames, no tools, JSON event mode.
- Launcher: `scripts/run_vistr_vllm_evals.sh` with checkpoint/resume.

## Results

| Harness | Correct | Accuracy | Reasoning present | Final answer present |
|---|---:|---:|---:|---:|
| Baseline direct | 192/403 | 47.6% | 403/403 | 350/403 |
| pi stage 1 | 189/403 | 46.9% | 403/403 | 354/403 |

Paired comparison: both correct 145, baseline-only 47, pi-only 44, both wrong 167.
The pi result is 3 fewer correct answers than baseline (-0.7 percentage points).

## Caveat

The 4096 output-token budget was exhausted on 53 baseline samples and 49 pi
samples: these records contain reasoning but no final answer and are counted as
wrong in the raw accuracy. A rerun of those IDs with a larger output budget is
needed for a clean comparison of answer quality.

## Outputs

- `outputs/predictions/baseline_qwen3-vl-8b-thinking_vllm_dev_trace.jsonl`
- `outputs/predictions/pi_qwen3-vl-8b-thinking_vllm_dev_trace.jsonl`
