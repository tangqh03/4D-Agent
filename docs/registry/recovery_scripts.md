# Recovery experiment registry

### `scripts/recover_missing_vllm_answers.py`

**Purpose**: Extract samples with empty `final_answer` fields from the original baseline/pi traces, rerun them through the configured vLLM endpoint with a larger budget, and merge non-empty recovery answers back into the 403-row public-dev trace.

**Usage**:

```bash
VISTR_PI_PROVIDER=vllm-local VISTR_PI_MODEL=qwen3-vl-8b-thinking PI_OFFLINE=1 \
  /opt/conda/envs/311/bin/python -u scripts/recover_missing_vllm_answers.py \
  --harness baseline|pi|both --split dev --max-tokens 16384|32768 --workers 8
```

**Inputs**: Original `outputs/predictions/*_trace.jsonl`, ViSTR-Bench public dev data, and `agent/llm_keys.local.json`.

**Outputs**: `outputs/recovery/*_recovery.jsonl` and `outputs/predictions/*_recovered_merged.jsonl`.

**Notes**: Recovery is resumable by ID. The merge replaces an original row only when its latest recovery has a non-empty `final_answer`; otherwise the original row is retained.
