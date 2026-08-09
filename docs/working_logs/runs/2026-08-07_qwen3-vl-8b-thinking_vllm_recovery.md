# ViSTR-Bench recovery run: Qwen3-VL-8B-Thinking via vLLM

- Date: 2026-08-07
- Split: public dev (403 samples)
- Model: `/data/Qwen3-VL-8B-Thinking/`
- Backend: vLLM, served as `qwen3-vl-8b-thinking` at `http://127.0.0.1:8001/v1`
- vLLM config: `configs/vllm_qwen3_vl_8b_thinking_recovery_8gpu.json`
- GPUs: `CUDA_VISIBLE_DEVICES=0,1,2,3,4,5,6,7`, tensor parallel size 8
- `max_model_len`: 61440
- Persistent serving session: `tmux vllm` (left running)

## Recovery procedure

The original traces had empty `final_answer` fields for 53 baseline items and 49 pi items. The recovery script extracted those IDs and ran them through the same vLLM endpoint.

- First recovery pass: `max_tokens=16384`, 8 workers.
- Baseline: 31/53 received a final answer; 22 remained empty.
- Pi: 49/49 received a final answer.
- Baseline residual pass: the remaining 22 items were rerun with `max_tokens=32768`, 8 workers.
- Final merge rule: use the latest non-empty recovery answer; retain the original trace when recovery is still empty.

## Final merged results

| Harness | Correct | Total | Accuracy | Final answers | Remaining empty |
|---|---:|---:|---:|---:|---:|
| baseline | 219 | 403 | 54.34% | 397 | 6 |
| pi | 220 | 403 | 54.59% | 403 | 0 |

Relative to the original traces, baseline improved from 192/403 (47.64%) to 219/403 (54.34%), and pi improved from 189/403 (46.90%) to 220/403 (54.59%).

The six baseline items still without a final answer after 32K are IDs 239, 899, 979, 364, 1205, and 712. Their tasks are respectively `Ego_Motion`, `Ego_Motion`, `Mikado_Dependency`, `Relative_Velocity`, `Rotation_Direction`, and `Swimming_Race`.

## Outputs

- Baseline recovery trace: `outputs/recovery/baseline_qwen3-vl-8b-thinking_vllm_dev_recovery.jsonl`
- Pi recovery trace: `outputs/recovery/pi_qwen3-vl-8b-thinking_vllm_dev_recovery.jsonl`
- Baseline merged trace: `outputs/predictions/baseline_qwen3-vl-8b-thinking_vllm_dev_recovered_merged.jsonl`
- Pi merged trace: `outputs/predictions/pi_qwen3-vl-8b-thinking_vllm_dev_recovered_merged.jsonl`
