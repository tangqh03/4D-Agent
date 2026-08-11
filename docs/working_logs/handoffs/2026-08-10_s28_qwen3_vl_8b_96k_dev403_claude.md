# Handoff — Claude Code 执行 S2.8 × qwen3-vl-8b-thinking 96k dev403

- Date: 2026-08-10
- Status: **completed（2026-08-11 00:49，dev403 全量 224/403 = 55.6%）**
- Executor: Claude Code
- Workspace: `/workspace/Spatial-Agent/4D-Agent`
- Dataset boundary: 只运行 ViSTR-Bench public dev 403，禁止 private eval

## 目标与固定边界

在当前本地 vLLM 上完成一次 S2.8 public dev403 全量。S2.8 固定为只加载
`agent/pi_ext/vistr_video_tools.ts`：不得加载 `evidence_closure.ts` 或
`evidence_ledger.ts`，不得加入 task routing、prompt tuning 或答案后处理。不要覆盖历史输出。

唯一主输出路径：

```text
outputs/predictions/pi_s28_qwen3-vl-8b-thinking_vllm_gpu0-3_96k_dev403_20260810.jsonl
```

若该文件不存在则新运行；若存在且不足 403 个唯一 ID，只能对同一路径加 `--resume`；
若已完整则只审计，不重跑、不删除。

## 已完成门禁

- Node extension suite：98/98。
- Python parser/prompt suite：23/23。
- py_compile、96k launcher dry-run、git diff check：通过。
- 真实视频段：semantic crop → H.264 zoomed MP4 → 递归读取 3 帧，2/2 工具成功。
- Public IDs 1/114/229：3/3 有合法 FINAL，14/14 工具执行，0 tool/provider error，
  0 no-answer、0 submit_answer；1/3 accuracy 不是门禁。
- 证据见 `docs/working_logs/runs/2026-08-10_s28_qwen3_vl_8b_96k_smoke.md`。

## 当前服务与配置

| 组件 | 状态 | 资源 |
|------|------|------|
| vLLM | tmux `vllm-96k`，`:8001` | GPU 0–3，TP=4，`max_model_len=98304`，`max_num_seqs=16` |
| perception | tmux `perception-s26`，`:7876` | GPU 6，GroundingDINO loaded |

- vLLM 可复现配置：`configs/vllm_qwen3_vl_8b_thinking_gpu0-3_96k.json`。
- `~/.pi/agent/models.json`：`contextWindow=98304`、`maxTokens=32768`、base URL
  `http://127.0.0.1:8001/v1`；不得输出其中 API key。
- `~/.pi/agent/settings.json`：`compaction.reserveTokens=32768`。
- pi 累积式 tool args 补丁当前存在；npm 更新后需重跑
  `/opt/conda/bin/python scripts/patch_pi_cumulative_args.py`。
- 全量结束后保留服务，除非负责人另行要求。

## Phase 1 — 全量前复核

```bash
cd /workspace/Spatial-Agent/4D-Agent
git status --short
node agent/pi_ext/tests/run.mjs
/opt/conda/bin/python agent/tests/test_eval_pi_parse.py
/opt/conda/bin/python -m py_compile agent/eval_pi_agentic.py scripts/launch_vllm_qwen3_vl_8b_thinking.py
git diff --check

curl -fsS http://127.0.0.1:8001/v1/models
curl -fsS http://127.0.0.1:7876/health
nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv,noheader
ss -ltnp | rg ':(8001|7876)\b'
/opt/conda/bin/python -c 'from agent.eval_baseline import load_samples; print(len(load_samples("dev")))'
rg -n 'PATCHED \(ViSTR\)' third_party/pi-runtime/node_modules/@earendil-works/pi-coding-agent/node_modules/@earendil-works/pi-ai/dist/api/openai-completions.js
```

必须看到 dev=403、served model 为 `qwen3-vl-8b-thinking`、`max_model_len=98304`、
perception loaded，以及累积式 args patch。若端口已被占用但服务不健康，先读 tmux/
日志并确认进程归属；不要启动第二实例或杀不明进程。

服务确实停止时，使用仓库配置恢复：

```bash
tmux new-session -d -s vllm-96k -c /workspace/Spatial-Agent/4D-Agent \
  '/opt/conda/envs/311/bin/python -u scripts/launch_vllm_qwen3_vl_8b_thinking.py \
  --config configs/vllm_qwen3_vl_8b_thinking_gpu0-3_96k.json \
  --python /opt/conda/envs/311/bin/python > /tmp/vllm_gpu0-3_96k.log 2>&1'
```

Perception 仅在 `:7876` 不健康且 GPU 6 可用时恢复，沿用现有 `perception-s26` 的
`GDINO_PATH` 和启动命令；不要猜测或下载新权重。

## Phase 2 — 启动或续跑 dev403

新运行：

```bash
tmux new-session -d -s s28-8b-dev403-96k -c /workspace/Spatial-Agent/4D-Agent \
  'env VISTR_PI_PROVIDER=vllm-local VISTR_PI_MODEL=qwen3-vl-8b-thinking \
  VISTR_CAPTION_PROVIDER=vllm-local VISTR_CAPTION_MODEL=qwen3-vl-8b-thinking \
  VISTR_PI_EXTENSION=agent/pi_ext/vistr_video_tools.ts \
  /opt/conda/bin/python -u agent/eval_pi_agentic.py --split dev \
  --workers 3 --timeout 900 \
  --output outputs/predictions/pi_s28_qwen3-vl-8b-thinking_vllm_gpu0-3_96k_dev403_20260810.jsonl \
  > /tmp/eval_s28_8b_dev403_96k_20260810.log 2>&1'
```

续跑使用完全相同命令并增加 `--resume`。96k KV 实测容量约 3.7 个并发序列，固定
`--workers 3`，不要提高。每 5–10 分钟检查：

```bash
tail -n 30 /tmp/eval_s28_8b_dev403_96k_20260810.log
wc -l outputs/predictions/pi_s28_qwen3-vl-8b-thinking_vllm_gpu0-3_96k_dev403_20260810.jsonl
curl -fsS http://127.0.0.1:8001/health
curl -fsS http://127.0.0.1:7876/health
nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv,noheader
```

单题答案错误、长思考或短时间无新行不是停止条件。仅在服务退出、持续 OOM/NCCL、
端口失联、输出损坏或误用 private split 时停止并调查。

## Phase 3 — 完整性审计

```bash
/opt/conda/bin/python - <<'PY'
import collections, json
from agent.eval_baseline import load_samples

path = "outputs/predictions/pi_s28_qwen3-vl-8b-thinking_vllm_gpu0-3_96k_dev403_20260810.jsonl"
rows = [json.loads(line) for line in open(path) if line.strip()]
expected = {sample["id"] for sample in load_samples("dev")}
ids = [row["id"] for row in rows]

assert len(rows) == 403
assert len(set(ids)) == 403
assert set(ids) == expected
assert not [row for row in rows if row.get("src") == "error"]
assert not [row["id"] for row in rows if row.get("no_answer")]
assert all(row.get("pred") in row.get("options", []) for row in rows)
assert all(row["tools_executed"] == row["tool_calls"] for row in rows)
assert sum(row["tool_errors"] for row in rows) == 0
assert sum(row["termination"]["provider_error_count"] for row in rows) == 0
assert not [
    (row["id"], call) for row in rows for call in row.get("tool_trace", [])
    if call.get("name") == "submit_answer"
]

print("accuracy", sum(row["correct"] for row in rows), "/", len(rows))
print("answer_source", collections.Counter(row["answer_source"] for row in rows))
print("stop_reason", collections.Counter(row["termination"]["stop_reason"] for row in rows))
print("tools", sum(row["tool_calls"] for row in rows),
      sum(row["tools_executed"] for row in rows))

by_task = collections.defaultdict(lambda: [0, 0, 0.0])
for row in rows:
    by_task[row["task"]][0] += int(row["correct"])
    by_task[row["task"]][1] += 1
    by_task[row["task"]][2] += row.get("elapsed_s", 0)
for task in sorted(by_task):
    correct, total, elapsed = by_task[task]
    print(task, f"{correct}/{total}", f"{correct/total:.1%}", f"avg={elapsed/total:.1f}s")
PY

rg -n 'maximum context length|HTTP/1.1" 400|spawn ffprobe ENOENT|Traceback|NCCL|CUDA out of memory' \
  /tmp/vllm_gpu0-3_96k.log /tmp/perception_s26_64k.log \
  /tmp/eval_s28_8b_dev403_96k_20260810.log
```

硬门禁：精确 403 个 public-dev ID、0 error/no-answer/provider error/tool error、所有
tool call 均执行、所有预测属于原选项、0 submit_answer。若失败，不得手工补答案或用
GT/reasoning 改写结果；记录 ID 和根因后，仅对明确基础设施失败做独立 recovery run。
Accuracy、micro/macro、per-task 和预测分布只报告，不作为基础设施门禁。

## Phase 4 — 收尾

1. 新建全量 run log，记录命令、服务配置、总耗时、micro/macro/per-task、预测分布、
   answer source、termination、工具调用与所有异常 ID。
2. 更新 `docs/registry/outputs.md`、`docs/working_logs/active.md`，把本 handoff 状态改为 completed。
3. 全量结果不得用于 private split 调参；若后续改代码/参数，必须使用新输出名和新 run log。
4. 默认保留 vLLM/Perception 和当前 pi 配置供复核。

## 已知注意事项

- 主模型不保证主动调用视频段 crop；这是策略选择，不是工具失败。视频段能力已有真实探针。
- GroundingDINO 对某些采样点可能无候选；S2.8 允许 3 个时间点中至少 1 个成功。
- direct pi 必须继承当前 Node PATH，并前置 `/opt/conda/bin` 与
  `/opt/conda/envs/spatialagent/bin`；正式 eval 脚本已自动处理。
- 不要把 3 题 smoke 的 1/3 accuracy 当作全量预期或调参依据。
