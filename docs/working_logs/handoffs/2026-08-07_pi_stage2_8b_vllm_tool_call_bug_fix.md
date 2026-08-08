---
status: resolved
scope: evaluation-bug-fix
last_updated: 2026-08-08
owner: gaozhe
---

# Handoff — pi Stage 2 × 8b-thinking vLLM 工具调用 bug 修复

## 一句话现状

**已完成 (2026-08-08)**:三个 bug 全部根除。Bug C（裸 JSON 工具调用被吞进 thinking）根因确认为**模型自身输出行为**（多轮工具上下文的新回合开头，模型直接输出 `{"name":...}</tool_call>` 而漏掉 `<tool_call>` 开标签，151657 出现 0 次），并已在 **vLLM serving 层**找到可靠修复点（`parse_delta` 检测"请求开头 + 配 tools + 流以 `{"` 开头"→ 重建开标签），冒烟测试 **10/10 PASS、swallowed 恒为 0**（修复前 2/4 FAIL）。无需方案 B。vLLM 已无 debug 运行于 `tmux vllm`（port 8001，健康）。详见 [run log](runs/2026-08-08_pi_8b_vllm_tool_call_bare_json_fix.md)。

## 已完成的工作

### 1. 核心功能：pi Stage 2 × 8b-thinking 全量评测

| 项 | 值 |
|----|-----|
| 脚本 | `agent/eval_pi_agentic.py` |
| 模型 | `qwen3-vl-8b-thinking` via 本地 vLLM TP=8 port 8001 |
| 配置 | `configs/vllm_qwen3_vl_8b_thinking_recovery_8gpu.json` |
| 工具解析 | `--enable-auto-tool-choice --tool-call-parser hermes` |
| 推理解析 | `--reasoning-parser qwen3` |
| 结果 | **50.4% (203/403)**，6 errors |
| 输出 | `outputs/predictions/pi_agentic_qwen3-vl-8b-thinking_vllm_dev.jsonl` |
| Run log | `docs/working_logs/runs/2026-08-07_pi_stage2_8b_vllm_dev.md` |

### 2. 已修复的 Bug（根除）

#### Bug A：ffprobe/ffmpeg 找不到
- **根因**：pi 子进程 PATH 不含 ffmpeg；prompt 却宣称"ffprobe/ffmpeg 已装"
- **修复**：`agent_env()` 在 `eval_pi_agentic.py:45-52`，prepend `/opt/conda/bin`(cv2 4.13) + `/opt/conda/envs/spatialagent/bin`(ffmpeg 8.1.2)
- **验证**：`command not found` 从 98% → 2%

#### Bug B：Prompt 误导模型
- **修复**：prompt 诚实描述工具 + 禁止 `which`/`whereis`/`find /`（见 `eval_pi_agentic.py:55-70`）

### 3. 已修复的 Bug（根除）

#### Bug C：vLLM reasoning_parser 间歇性吞 tool_call

> **2026-08-08 根因调查**（两个方向互补）：
> - 机制侧（remnant 视角）：[run log](runs/2026-08-08_pi_stage2_remnant_root_cause.md)
> - 修复侧（serving 层）：[run log](runs/2026-08-08_pi_8b_vllm_tool_call_bare_json_fix.md)

- **真实机制**：8b-thinking 模型在**多轮工具上下文**（toolResult 之后）的新回合开头，有时直接输出完整工具 JSON + `</tool_call>`，但**不输出 `<tool_call>` opening tag**（logprobs token 流中 151657 出现 0 次，151658 出现多次；debug 日志证实裸 JSON 是**该请求第一个 delta**，`prev_tail=''`，无 reasoning、无 `</think>`）。vLLM qwen3 parser 对 151658 的处理是**正确**的（它不是 reasoning-end 标记）→ JSON+closing 作为 reasoning 忠实输出 → pi thinking 块含 remnant
- **触发率**：真实 agentic 会话 254/694（37%），round 分布 round1=1 / round2=96 / round3+ 分散；与工具调用行为强相关（修复 Bug A/B 前模型不用工具，0% remnant）。stochastic（temperature=1.0），单轮/重放实验 0 复现
- **影响**：remnant 里的工具调用 pi 不执行 → 模型误以为已执行 → 后续推理基于幻觉状态；全量 eval 已计入 `_repair_swallowed_tool_calls`（从 thinking 提取 JSON 恢复计数与答案提取），但**无法让 pi 真正执行工具**
- **修复（2026-08-08 完成）**：reasoning parser 确实无法区分"讨论 JSON"与"实际调用"，但 **serving 层 `DelegatingParser.parse_delta` 可以**——裸 JSON 只出现在工具请求的**流开头**（与 mid-thinking 讨论 JSON 可区分）。修复：检测"请求配 tools + tool_choice∈{auto,None} + `previous_text` 为空 + delta 以 `{"` 开头"→ 立即结束 reasoning 相位并把 `<tool_call>` 开标签重建到 content 流（`abstract_parser.py`）。单元测试 6/6，冒烟 **10/10 PASS**（修复前 2/4 FAIL），真实流量重建事件 5+ 次。eval 侧 `_repair_swallowed_tool_calls` 保留作兜底

## vLLM 源码修改（已生效并验证，2026-08-08）

### 核心修复：`/workspace/vllm-src/vllm/parser/abstract_parser.py`（serving 层）

`DelegatingParser.parse_delta` 的 reasoning 相位入口新增裸 JSON 工具调用检测：

```python
if (not state.previous_text.strip()          # 流开头（该请求的第一个 delta）
        and delta_text.lstrip().startswith('{"')   # 裸 JSON 体
        and getattr(request, "tools", None)        # 请求配了工具
        and getattr(request, "tool_choice", None) in (None, "auto")
        and self._tool_parser is not None):
    # 结束 reasoning 相位，重建 <tool_call> 开标签到 content 流，
    # 让 hermes tool parser 正常提取工具调用
    delta_message = DeltaMessage(content=tool_parser.tool_call_start_token + delta_text)
```

门控刻意收窄：仅"工具请求的流开头 + `{"`"，推理中途的 JSON 讨论不触发（单元测试覆盖）。

### 配套修改：`/workspace/vllm-src/vllm/reasoning/qwen3_reasoning_parser.py`

上一轮的 string-level 兜底（`</think>`/`<tool_call>` 拆 token 输出场景 + tool_call 优先于迟到 `</think>`）保留。真实失败中从未触发（`</think>` 均以特殊 token 形式出现），但与 serving 层修复互补，单元测试 9/9 保持通过。

### 验证结论

| 验证 | 结果 |
|------|------|
| 单元测试（parse_delta 6 场景 + qwen3 parser 9 场景） | 15/15 PASS |
| 冒烟测试修复前基线（正确覆盖 local vLLM） | 2/4 FAIL（tc=1, swallowed=1） |
| 冒烟测试修复后（debug 重启） | 6/6 PASS，重建事件 5+ 次 |
| 冒烟测试最终（clean 重启，无 debug） | 4/4 PASS |
| 合计 | **10/10 PASS，swallowed 恒为 0** |

### 冒烟测试命令（必须带覆盖变量，否则走远程 amap 模型）

```bash
VISTR_PI_PROVIDER=vllm-local VISTR_PI_MODEL=qwen3-vl-8b-thinking \
  /opt/conda/bin/python /tmp/pi_smoke_test_20260807.py
```

## 备选方案 B（暂不需要——vLLM 修复已生效）

原方案（eval harness 实时 interception：检测被吞 tool_call → 注入 tool_result → 继续循环）不再需要用于本 bug。`_repair_swallowed_tool_calls` post-hoc recovery 保留作兜底（应对"裸 JSON 永不闭合"等 parser 层无法恢复的模型跑飞情况）。

## 关键文件

| 文件 | 作用 |
|------|------|
| `agent/eval_pi_agentic.py` | Stage 2 核心脚本（含 PATH/env 修复 + recovery） |
| `/workspace/vllm-src/vllm/parser/abstract_parser.py` | **核心修复**：裸 JSON 工具调用重建开标签（已验证） |
| `/workspace/vllm-src/vllm/reasoning/qwen3_reasoning_parser.py` | string-level 兜底（保留，与上述互补） |
| `configs/vllm_qwen3_vl_8b_thinking_recovery_8gpu.json` | vLLM 启动配置 |
| `scripts/launch_vllm_qwen3_vl_8b_thinking.py` | vLLM 启动器（支持 --enable-auto-tool-choice） |
| `~/.pi/agent/models.json` | pi provider 配置（vllm-local, maxTokens=32768，已恢复 8001） |
| `scripts/patch_pi_cumulative_args.py` | pi 累积式参数补丁（npm 重装后需重跑） |
| `outputs/predictions/pi_agentic_qwen3-vl-8b-thinking_vllm_dev.jsonl` | 全量结果 |
| `outputs/predictions/pi_agentic_8b_vllm_dev.buggy_ids.json` | 65 个 buggy 样本 ID |
| `outputs/predictions/pi_agentic_8b_vllm_dev_buggy_rerun.jsonl` | buggy 样本重跑结果 |
| `docs/working_logs/runs/2026-08-07_pi_stage2_8b_vllm_dev.md` | 全量 Run log |
| `docs/working_logs/runs/2026-08-08_pi_stage2_remnant_root_cause.md` | 根因调查（机制/触发率） |
| `docs/working_logs/runs/2026-08-08_pi_8b_vllm_tool_call_bare_json_fix.md` | 本修复 Run log |

## 启动前检查清单

1. vLLM 在 8001 端口活着：`curl -s http://127.0.0.1:8001/health`
2. pi 补丁在：`grep "PATCHED (ViSTR)" third_party/pi-runtime/node_modules/@earendil-works/pi-coding-agent/node_modules/@earendil-works/pi-ai/dist/api/openai-completions.js`
3. 自检通过：`/opt/conda/bin/python -c "import agent.eval_pi_agentic as E; E._self_check()"`

## 对比基线

| 配置 | Accuracy |
|------|----------|
| Stage 2 + qwen3-vl-plus (AMAP) | 53.8% (217/403) |
| **Stage 2 + 8b-thinking (vLLM)** | **50.4% (203/403)** |
| Baseline + 8b-thinking (vLLM) | 50.6% (192/403) |
| Stage 1 + 8b-thinking (vLLM) | 46.9% (189/403) |
