# 全量 dev 403 重跑 — vLLM 裸 JSON 修复后验证

- Date: 2026-08-08
- Split: public dev (403 samples)
- Model: `qwen3-vl-8b-thinking` via 本地 vLLM TP=8 port 8001(**含 2026-08-08 的 serving 层修复**)
- Harness: pi agentic(`agent/eval_pi_agentic.py`)
- Command: `VISTR_PI_PROVIDER=vllm-local VISTR_PI_MODEL=qwen3-vl-8b-thinking /opt/conda/bin/python agent/eval_pi_agentic.py --split dev --workers 4 --timeout 600 --output outputs/predictions/pi_agentic_qwen3-vl-8b-thinking_vllm_dev_fix.jsonl`
- 对比基线: `outputs/predictions/pi_agentic_qwen3-vl-8b-thinking_vllm_dev.jsonl`(**50.4%, 203/403**,修复前)
- 启动时间: 2026-08-08 00:20,后台任务 bp4j9j79j,日志 `/tmp/eval_full_dev_20260808.log`

## 目的

验证 Bug C 根治(vLLM serving 层重建 `<tool_call>` 开标签,见
`2026-08-08_pi_8b_vllm_tool_call_bare_json_fix.md`)对全量准确率的实际提升。
预期: 修复前 50.4%,~14% 样本 early_term(工具调用被吞),修复后 early_term
应显著下降、准确率 +0.5pp 级。

## 状态: 已完成(第二次启动,2026-08-08)

- 首次启动 00:20(旧代码,无轨迹),40 行后经用户确认于 00:5x 终止,
  部分输出移为 `pi_agentic_qwen3-vl-8b-thinking_vllm_dev_fix.aborted_20260808.jsonl`
- **重启 00:5x**:新代码(轨迹落盘 + 执行校验),任务 bijk3grx8,
  日志 `/tmp/eval_full_dev_20260808_v2.log`。~4.2h 跑完 403 样本(37.4s/样本,
  8 个 600s 超时)

## 轨迹落盘与执行校验(2026-08-08)

`agent/eval_pi_agentic.py` 新增字段:
- `tool_trace`: 每次工具调用的 name + arguments(实际 bash command 全文)
- `tool_results`: tool_execution_end 的 isError + content(read 图片以
  `{"type":"image","data_bytes":N}` 记录,防 base64 爆量)
- `tools_executed`: trace 中匹配到执行结果的调用数(未匹配 = 被吞/未执行,Bug C 度量)
- `tool_errors`: isError=true 的执行数
校验工具 `/tmp/check_tool_execution.py`(按 toolCallId 配对 trace ↔ results)。

冒烟结果:
- 回放真实事件流 `/tmp/pi_trace_events.jsonl`:11/11 调用、11/11 执行、0 error、0 空
- live 冒烟:`VISTR_PI_PROVIDER=vllm-local VISTR_PI_MODEL=qwen3-vl-8b-thinking
  /opt/conda/bin/python agent/eval_pi_agentic.py --ids 1 --output /tmp/pi_trace_smoke_out.jsonl`
  → 4/4 调用、4/4 执行、0 error(命令 + 输出全文落盘)
- 注意:模型中途 ffmpeg 参数错误的输出也在 content 里(isError 只标硬失败),分析时看 content 全文

## 结果

| 指标 | 修复前 (2026-08-07) | 修复后 (本次) |
|------|--------|--------|
| Accuracy | 50.4% (203/403) | **51.4% (207/403)** |
| 吞工具样本 (调用了但未执行) | ~14% (57/397) | **0** (3590/3590 全部执行) |
| 平均工具调用/样本 | 12.7 | 8.9 (调用不再被吞,agent 收敛更快) |
| error (600s 超时) | 6 | 8 |
| 使用工具的样本 | — | 395/403 (98%) |
| isError / 空结果执行 | — | 0 / 0 (isError 只标硬失败,命令 stderr 输出在 content 里) |

Per-task(修复后):
| Task | Acc | Task | Acc |
|------|-----|------|-----|
| Passage_Feasibility | 69% | Billiards_Shot | 52% |
| Interaction_Direction | 59% | Golf_Shot | 50% |
| Swimming_Race | 59% | Knot_Type | 50% |
| Vehicle_Movement | 59% | Rotation_Direction | 48% |
| Ego_Motion | 57% | Mikado_Dependency | 48% |
| Fall_Direction | 57% | Relative_Velocity | 44% |
| Soccer_Shot | 53% | Basketball_Shot | 41% |
| | | Jenga_Stability | 40% |

## 工具执行校验(用户要求:确认工具真的正确执行)

校验器 `/tmp/check_tool_execution.py`(trace ↔ results 按 toolCallId 配对):

```
samples using tools    : 395/403 (98.0%)
tool calls made        : 3590
calls actually executed: 3591 (100.0%)   # 多出 1 条执行无对应 trace 条目,可忽略
calls NOT executed     : 0
executions with isError: 0
executions empty result: 0
```

结论:全量上**每一次工具调用都被 pi 真实执行**——Bug C(工具调用被 reasoning parser
吞掉、模型基于幻觉状态继续推理)在 serving 层修复后归零,且准确率 +1.0pp。
注意 isError 语义:模型自己写的 ffmpeg 参数错误等 stderr 输出仍进 content
(如 trace 中可见反复试错),isError 只标记硬失败。
