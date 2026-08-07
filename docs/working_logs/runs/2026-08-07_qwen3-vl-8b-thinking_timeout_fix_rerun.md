# ViSTR-Bench timeout-fix rerun

- Date: 2026-08-07
- Harness: baseline
- Samples: the six IDs that previously failed at the 32K recovery pass
- Model endpoint: `qwen3-vl-8b-thinking` via the persistent `tmux vllm` service on port 8001
- Command budget: `max_tokens=32768`
- Request timeout: `1800s`

## Code fix

`--timeout` now defaults to 1800 in `scripts/recover_missing_vllm_answers.py`, and the baseline recovery branch forwards it to `solve_baseline` and `agent.llm.chat`. Previously baseline used the client default of 180 seconds regardless of the recovery CLI value.

## Outcome

All six requests completed without a runtime timeout. Each consumed the full 32768 completion-token budget, but each still returned an empty final answer. The affected IDs remain 239, 364, 712, 899, 979, and 1205.

The merged baseline result therefore remains 219/403 (54.34%), with 397 non-empty final answers and 6 empty final answers. The vLLM service and `tmux vllm` session were left running.

## Outputs

- Recovery trace: `outputs/recovery/baseline_qwen3-vl-8b-thinking_vllm_dev_recovery.jsonl`
- Merged trace: `outputs/predictions/baseline_qwen3-vl-8b-thinking_vllm_dev_recovered_merged.jsonl`
