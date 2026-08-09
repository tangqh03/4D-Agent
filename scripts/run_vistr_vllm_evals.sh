#!/usr/bin/env bash
set -euo pipefail

# Run the direct baseline and the pi stage-1 harness against the same local
# Qwen3-VL vLLM server. Both evaluators write JSONL checkpoints and can resume.

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${VISTR_PYTHON:-/opt/conda/envs/311/bin/python}"
VLLM_PYTHON="${VLLM_PYTHON:-$PYTHON_BIN}"
MODEL="${VISTR_MODEL:-qwen3-vl-8b-thinking}"
BASE_URL="${VISTR_LLM_BASE_URL:-http://127.0.0.1:8001/v1}"
PROVIDER="${VISTR_PI_PROVIDER:-vllm-local}"
SPLIT="${VISTR_SPLIT:-dev}"
MAX_TOKENS="${VISTR_MAX_TOKENS:-4096}"
PI_WORKERS="${VISTR_PI_WORKERS:-4}"
LIMIT="${VISTR_LIMIT:-}"
TASKS="${VISTR_TASKS:-}"
VLLM_CONFIG="${VLLM_CONFIG:-$PROJECT_DIR/configs/vllm_qwen3_vl_8b_thinking.json}"

OUTPUT_DIR="$PROJECT_DIR/outputs/predictions"
LOG_DIR="$PROJECT_DIR/outputs/logs"
mkdir -p "$OUTPUT_DIR" "$LOG_DIR"

BASELINE_OUTPUT="${VISTR_BASELINE_OUTPUT:-$OUTPUT_DIR/baseline_${MODEL}_vllm_${SPLIT}_trace.jsonl}"
PI_OUTPUT="${VISTR_PI_OUTPUT:-$OUTPUT_DIR/pi_${MODEL}_vllm_${SPLIT}_trace.jsonl}"
RUN_LOG="$LOG_DIR/run_vllm_evals_${SPLIT}_$(date +%Y%m%d_%H%M%S).log"

usage() {
  sed -n '2,14p' "$0"
  cat <<'EOF'

Environment overrides:
  VISTR_LIMIT=5              smoke-test limit (unset means the full split)
  VISTR_PI_WORKERS=4         pi concurrency
  VISTR_MAX_TOKENS=4096      output budget for both harnesses
  VISTR_SPLIT=dev            dev, eval, or all
  VISTR_BASELINE_OUTPUT=...  baseline JSONL checkpoint path
  VISTR_PI_OUTPUT=...        pi JSONL checkpoint path

Examples:
  bash scripts/run_vistr_vllm_evals.sh
  VISTR_LIMIT=5 bash scripts/run_vistr_vllm_evals.sh
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi
if [[ $# -gt 0 ]]; then
  echo "Unexpected arguments: $*" >&2
  usage >&2
  exit 2
fi

exec > >(tee -a "$RUN_LOG") 2>&1

server_status() {
  "$PYTHON_BIN" - "$BASE_URL/models" "$MODEL" <<'PY'
import json
import sys
import urllib.request
import urllib.error

url, expected = sys.argv[1:]
try:
    with urllib.request.urlopen(url, timeout=5) as response:
        payload = json.load(response)
except (OSError, ValueError, urllib.error.URLError):
    print("unavailable")
    raise SystemExit(0)

ids = {item.get("id") for item in payload.get("data", [])}
print("ready" if expected in ids else "wrong-model")
PY
}

status="$(server_status)"
if [[ "$status" == "wrong-model" ]]; then
  echo "ERROR: $BASE_URL is reachable but does not serve $MODEL" >&2
  exit 1
fi

if [[ "$status" != "ready" ]]; then
  VLLM_LOG="$LOG_DIR/vllm_${MODEL}_$(date +%Y%m%d_%H%M%S).log"
  echo "vLLM is not ready; starting it with $VLLM_CONFIG"
  "$PYTHON_BIN" "$PROJECT_DIR/scripts/launch_vllm_qwen3_vl_8b_thinking.py" \
    --config "$VLLM_CONFIG" --python "$VLLM_PYTHON" >"$VLLM_LOG" 2>&1 &
  vllm_pid=$!
  echo "vLLM PID: $vllm_pid; log: $VLLM_LOG"

  wait_seconds="${VLLM_WAIT_SECONDS:-600}"
  elapsed=0
  until [[ "$(server_status)" == "ready" ]]; do
    if ! kill -0 "$vllm_pid" 2>/dev/null; then
      echo "ERROR: vLLM exited before becoming ready" >&2
      tail -n 80 "$VLLM_LOG" >&2 || true
      exit 1
    fi
    if (( elapsed >= wait_seconds )); then
      echo "ERROR: vLLM did not become ready within ${wait_seconds}s" >&2
      tail -n 80 "$VLLM_LOG" >&2 || true
      exit 1
    fi
    sleep 5
    elapsed=$((elapsed + 5))
  done
fi

echo "vLLM ready: $BASE_URL ($MODEL)"
echo "Baseline output: $BASELINE_OUTPUT"
echo "pi output: $PI_OUTPUT"

baseline_cmd=(
  "$PYTHON_BIN" -u "$PROJECT_DIR/agent/eval_baseline.py"
  --split "$SPLIT" --resume --max-tokens "$MAX_TOKENS"
  --output "$BASELINE_OUTPUT"
)
if [[ -n "$LIMIT" ]]; then
  baseline_cmd+=(--limit "$LIMIT")
fi
if [[ -n "$TASKS" ]]; then
  baseline_cmd+=(--tasks "$TASKS")
fi

echo "=== baseline: ${baseline_cmd[*]} ==="
VISTR_LLM_MODEL="$MODEL" "${baseline_cmd[@]}" 2>&1 | tee "$LOG_DIR/baseline_${MODEL}_${SPLIT}.log"

pi_cmd=(
  "$PYTHON_BIN" -u "$PROJECT_DIR/agent/eval_pi.py"
  --split "$SPLIT" --resume --workers "$PI_WORKERS"
  --timeout "${VISTR_PI_TIMEOUT:-300}" --output "$PI_OUTPUT"
)
if [[ -n "$LIMIT" ]]; then
  pi_cmd+=(--limit "$LIMIT")
fi
if [[ -n "$TASKS" ]]; then
  pi_cmd+=(--tasks "$TASKS")
fi

echo "=== pi: ${pi_cmd[*]} ==="
VISTR_PI_PROVIDER="$PROVIDER" VISTR_PI_MODEL="$MODEL" PI_OFFLINE=1 \
  "${pi_cmd[@]}" 2>&1 | tee "$LOG_DIR/pi_${MODEL}_${SPLIT}.log"

echo "=== both evaluations completed ==="
echo "baseline: $BASELINE_OUTPUT"
echo "pi:       $PI_OUTPUT"
echo "run log:  $RUN_LOG"
