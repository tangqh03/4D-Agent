# Handoff — Claude Code 执行 S2.6 64k dev403 全量

- Date: 2026-08-09
- Status: **READY；定向 smoke 已通过，全量尚未启动**
- Executor: Claude Code
- Workspace: `/workspace/Spatial-Agent/4D-Agent`
- Dataset boundary: 只运行 ViSTR-Bench public dev 403，禁止 private eval

## 任务与不可变边界

目标是在现有健康服务上完成一次 S2.6 dev403 全量，验证 64k 上下文和本批 bugfix。
不要继续修改 closure 的 claim→answer 蕴含、对象一致性、时空覆盖或 one-shot 规则；
这些属于后续独立实验。不要覆盖任何历史输出，不要停止 7875/7877 viewer。

本次全量唯一输出路径固定为：

```text
outputs/predictions/pi_s26_qwen3-vl-8b-thinking_vllm_gpu0-3_64k_dev403_20260809.jsonl
```

若文件不存在，创建新运行；若存在且少于 403 个唯一 ID，只能对同一路径使用
`--resume`；若已经完整，直接审计，不重跑、不删除。

## 已修 bug

1. `index_video null.trim` / `semantic_crop null.match`：统一解析
   `content` 与 reasoning；null content 优雅失败，thinking 不作为答案。
2. selection subcall 预算 8→128，caption 1000→1500；候选 ID 只从 committed
   content 解析。
3. index caption 失败时 `caption_ok=false`，closure ledger 不再记录不存在的 timeline。
4. S2.6 无 FINAL 时，eval 从最后一次 `details.accepted=true` 的 `submit_answer`
   调用参数恢复；没有成功提交则 `pred=null`，禁止 reasoning 猜答案。
5. 输出保存 tool `details`、`answer_source/no_answer/termination`，provider context
   error 不再静默丢失。
6. `read_crop` 拦截 0-1 bbox，并说明固定 bbox 不是 tracker。
7. 服务窗口 40960→65536；pi client window 同步为 65536，compaction reserve=32768。

## 当前服务与外部配置

交接时状态：

| 组件 | tmux / PID | 资源 | 日志 |
|------|------------|------|------|
| vLLM | `vllm-64k` / API PID 274800 | GPU 0–3，TP=4，:8001，65536，max_num_seqs=16 | `/tmp/vllm_gpu0-3_64k.log` |
| perception | `perception-s26` / PID 274803 | GPU 6，:7876，GroundingDINO loaded | `/tmp/perception_s26_64k.log` |
| viewers | 独立进程 | :7875、:7877 | **勿动** |

服务可能因时间推移换 PID；以端口、tmux 和完整命令复核，不依赖旧 PID。

pi 配置：

- `~/.pi/agent/models.json`：`vllm-local/qwen3-vl-8b-thinking` 的
  `contextWindow=65536`、`maxTokens=32768`、base URL `http://127.0.0.1:8001/v1`。
- 备份：`~/.pi/agent/models.json.s26-64k-20260809.bak`（原 contextWindow=131072）。
- `~/.pi/agent/settings.json`：本轮前不存在；当前为 0600，
  `compaction.reserveTokens=32768`。
- 不输出或复制 models.json 中的 API key。

全量完成后默认保留服务和当前配置供复查。只有负责人决定切换服务时才恢复：先停止
对应服务，再 `cp -p` models 备份回原路径；因为 settings 原先不存在，将当前
settings 移到带时间戳的归档名，不要直接删除。

## 已完成门禁

- Node extension tests：93/93。
- Python parser tests：21/21。
- `py_compile`、`git diff --check`：通过。
- vLLM bare-JSON serving patch：6/6。
- 原失败题 `114,118,229,332,863,866,909`：7/7 完成，62/62 工具执行，
  0 tool error、0 provider error、0 null crash、0 context 400。
- Smoke 准确率 4/7 不是门禁。#332 本次模型自身提交并 FINAL Green；历史
  accepted Blue/no-FINAL 恢复路径由确定性单测覆盖。

Smoke 证据：

- Run log：`docs/working_logs/runs/2026-08-09_s26_bugfix_64k_smoke.md`
- Output：`outputs/predictions/pi_s26_fix_smoke_ids_114_118_229_332_863_866_909_20260809.jsonl`

## Phase 1 — 全量前只读复核

```bash
cd /workspace/Spatial-Agent/4D-Agent
git status --short
node agent/pi_ext/tests/run.mjs
/opt/conda/bin/python agent/tests/test_eval_pi_parse.py
/opt/conda/bin/python -m py_compile agent/eval_pi_agentic.py
git diff --check

curl -fsS http://127.0.0.1:8001/health
curl -fsS http://127.0.0.1:8001/v1/models
curl -fsS http://127.0.0.1:7876/health
nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv,noheader
ss -ltnp | rg ':(8001|7875|7876|7877)\b'
/opt/conda/bin/python -c 'from agent.eval_baseline import load_samples; print(len(load_samples("dev")))'
```

必须看到 dev=403、模型 `max_model_len=65536`、vLLM 只占 GPU 0–3、perception
只占 GPU 6、7875/7877 仍存活。若服务不健康，先读日志和 tmux；不要启动第二实例，
不要杀不明进程。

## Phase 2 — 启动或续跑 dev403

新运行：

```bash
tmux new-session -d -s s26-dev403-64k -c /workspace/Spatial-Agent/4D-Agent \
  'env VISTR_PI_PROVIDER=vllm-local VISTR_PI_MODEL=qwen3-vl-8b-thinking \
  VISTR_CAPTION_PROVIDER=vllm-local VISTR_CAPTION_MODEL=qwen3-vl-8b-thinking \
  VISTR_PI_EXTENSION=agent/pi_ext/vistr_video_tools.ts,agent/pi_ext/evidence_closure.ts \
  /opt/conda/bin/python -u agent/eval_pi_agentic.py --split dev --limit 403 \
  --workers 4 --timeout 900 \
  --output outputs/predictions/pi_s26_qwen3-vl-8b-thinking_vllm_gpu0-3_64k_dev403_20260809.jsonl \
  > /tmp/eval_s26_dev403_gpu0-3_64k_20260809.log 2>&1'
```

续跑仅在同一输出已部分存在时使用同样命令并增加 `--resume`。每 5–10 分钟检查：

```bash
tail -n 30 /tmp/eval_s26_dev403_gpu0-3_64k_20260809.log
wc -l outputs/predictions/pi_s26_qwen3-vl-8b-thinking_vllm_gpu0-3_64k_dev403_20260809.jsonl
curl -fsS http://127.0.0.1:8001/health
curl -fsS http://127.0.0.1:7876/health
nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv,noheader
```

不要因为单题错误答案、长思考或暂时无新 JSONL 行停止。需要停止的条件：vLLM/perception
进程退出、持续 OOM/NCCL error、端口失联、输出损坏或 private split 被误选。

## Phase 3 — 完整性和 bug 回归审计

运行结束后检查：

```bash
/opt/conda/bin/python - <<'PY'
import collections, json
from agent.eval_baseline import load_samples

path = "outputs/predictions/pi_s26_qwen3-vl-8b-thinking_vllm_gpu0-3_64k_dev403_20260809.jsonl"
rows = [json.loads(line) for line in open(path) if line.strip()]
expected = {sample["id"] for sample in load_samples("dev")}
ids = [row["id"] for row in rows]
assert len(rows) == 403
assert len(set(ids)) == 403
assert set(ids) == expected
assert not [row for row in rows if row.get("src") == "error"]
assert all(row["tools_executed"] == row["tool_calls"] for row in rows)
assert sum(row["tool_errors"] for row in rows) == 0
assert sum(row["termination"]["provider_error_count"] for row in rows) == 0

bad = ("null.trim", "null.match", "Cannot read properties of null")
assert not [
    row["id"] for row in rows for result in row["tool_results"]
    for content in result.get("content", [])
    if any(marker in str(content) for marker in bad)
]

print("accuracy", sum(row["correct"] for row in rows), "/", len(rows))
print("answer_source", collections.Counter(row["answer_source"] for row in rows))
print("no_answer", [row["id"] for row in rows if row["no_answer"]])
print("stop_reason", collections.Counter(row["termination"]["stop_reason"] for row in rows))
print("tools", sum(row["tool_calls"] for row in rows),
      sum(row["tools_executed"] for row in rows))

by_task = collections.defaultdict(lambda: [0, 0])
for row in rows:
    by_task[row["task"]][0] += int(row["correct"])
    by_task[row["task"]][1] += 1
for task in sorted(by_task):
    print(task, by_task[task])
PY

rg -n 'maximum context length|HTTP/1.1" 400|Cannot read properties of null|null\.trim|null\.match|Traceback|ERROR' \
  /tmp/vllm_gpu0-3_64k.log /tmp/perception_s26_64k.log \
  /tmp/eval_s26_dev403_gpu0-3_64k_20260809.log
```

硬通过条件：403 个精确 public-dev ID、无 `src=error`、每行 tools_executed 等于
tool_calls、0 tool error、0 provider error、0 null crash、0 context 400。

`no_answer` 不允许用 GT 或 reasoning 补写：逐 ID 检查其 termination 和 submit 轨迹，
确认“无合法 FINAL 且无 accepted submit”后保留 `pred=null` 并在 run log 报告。
准确率及预测分布用于结果报告，不作为基础设施硬门禁。

## Phase 4 — 收尾文档

Claude Code 完成后必须：

1. 新建 dev403 run log，记录命令、服务配置、总耗时、完整性、accuracy、per-task、
   answer_source/no_answer/termination、工具和 closure 统计。
2. 更新 `docs/registry/outputs.md`、`docs/working_logs/active.md`，把本 handoff 状态改为 completed。
3. 明确记录任何 no_answer/provider error 的 ID，不允许静默恢复。
4. 保留健康服务供复查；除非负责人要求切换，不恢复外部配置、不停止服务。

## 已知但不在本次全量中修的事项

- closure 只检查 evidence provenance，不能保证 claim 推出 answer（#901）。
- checker 对对象身份、空间内容和全时段覆盖不足（#114/#817）。
- 固定 bbox 不是目标跟踪；工具提示已增强，但未增加 tracker/内容有效性模型。
- #332 本次 smoke 的 Green 是模型决策错误，不是 accepted-submit 恢复错误。
