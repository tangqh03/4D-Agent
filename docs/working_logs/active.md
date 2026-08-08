---
status: active
last_updated: 2026-08-08
---

# ViSTR-Agent — Active Work State

## Current Focus: Bug C 已根治 — vLLM serving 层修复生效（2026-08-08）

**根因**（两方向互补调查）：8b-thinking 模型在多轮工具上下文的新回合**开头**直接输出
裸 `{"name":...}</tool_call>` 而漏掉 `<tool_call>` 开标签（151657 出现 0 次，stochastic，
触发率 37%，round2+ 为主）——是模型采样行为，reasoning parser 无解。

**修复**：`/workspace/vllm-src/vllm/parser/abstract_parser.py` `parse_delta` 检测
"配 tools 的请求 + 流开头 + `{"`" → 重建 `<tool_call>` 开标签进 content 流。
单元测试 15/15，冒烟 **10/10 PASS、swallowed 恒为 0**（修复前 2/4 FAIL）。
方案 B 不需要。eval 侧 `_repair_swallowed_tool_calls` 保留作兜底。
详见 `runs/2026-08-08_pi_8b_vllm_tool_call_bare_json_fix.md` + handoff（status: resolved）。

**vLLM 状态**：tmux `vllm` 中 clean 版运行中（2026-08-08 00:08 启动，pid 3410825，
envs/311，port 8001，健康，**含修复**，日志 `/tmp/vllm_launch_20260808_clean.log`）。
`~/.pi/agent/models.json` baseUrl **已恢复 8001**（8002 捕获代理已停，备份
`/tmp/models.json.bak`）。

**已完成**：全量 dev 403 重跑（任务 bijk3grx8，~4.2h）→ **51.4% (207/403)**，
修复前 50.4% (203/403)，**+1.0pp**。吞工具样本（调用但未执行）**0**（修复前 ~14%），
3590/3590 次工具调用全部真实执行，8 个 600s 超时（基线同类 6 个）。
输出 `outputs/predictions/pi_agentic_qwen3-vl-8b-thinking_vllm_dev_fix.jsonl`
（含 tool_trace/tool_results/tools_executed/tool_errors 轨迹字段）。
run log: `runs/2026-08-08_pi_8b_vllm_full_dev_rerun_after_fix.md`。

**工具轨迹落盘 + 执行校验（2026-08-08 完成）**：`eval_pi_agentic.py` 新增：
- `tool_trace`：每次调用的 name + arguments（实际 bash command 全文）
- `tool_results`：tool_execution_end 的 isError + content（read 图片以 data_bytes 计防爆量）
- `tools_executed`：trace 中能匹配到执行结果的调用数（未匹配 = 被吞/未执行，Bug C 度量）
- `tool_errors`：isError=true 的执行数
校验工具 `/tmp/check_tool_execution.py`（按 toolCallId 配对）。验证：回放真实事件流
11/11 执行 0 error；live 冒烟 4/4 执行 0 error。

## Current Focus: pi Stage 2 × 本地 vLLM 8b-thinking

**Stage 2 接入本地 qwen3-vl-8b-thinking（vLLM, TP=8, port 8001）**：`agent/eval_pi_agentic.py` + provider `vllm-local`。
冒烟通过（agent 用 bash/write 自主分析视频）。全量 dev 403 已完成
（**50.4%, 203/403**，输出 `outputs/predictions/pi_agentic_qwen3-vl-8b-thinking_vllm_dev.jsonl`）。
注意跑本地 vLLM 需 `VISTR_PI_PROVIDER=vllm-local VISTR_PI_MODEL=qwen3-vl-8b-thinking`（默认 amap-gateway）。

**关键改动**：
- vLLM 需 `--enable-auto-tool-choice --tool-call-parser hermes`（Qwen3-VL 输出
  `<tool_call>JSON</tool_call>` 格式，`hermes` parser 正则匹配；`qwen3_xml` 只认
  `<function>/<parameter>` XML 不适用）——launcher/config 已支持
- pi 累积式 args 补丁需重打：`/opt/conda/bin/python scripts/patch_pi_cumulative_args.py`

## Current Focus: pi 作为新 harness

SpatialClaw 判定过于死板,换用 pi (https://github.com/earendil-works/pi) 作为新 baseline harness。

**Stage 1 已完成 (2026-08-06)**: `agent/eval_pi.py`(抽 8 帧 → `pi -p` 带图问答)。
全量 dev **54.6% (220/403)**。计划书: `plans/completed/0806-[pi作为harness]stage1-拉通.md`。

**Stage 2 已完成 (2026-08-07)**: `agent/eval_pi_agentic.py` — pi 原生工具集,
workspace + video.mp4,agent 自主 ffprobe/ffmpeg 抽帧 + read 看图(均 14.7 轮/题)。
全量 dev **53.8% (217/403)**。关键修复: 网关流式 tool-call args 为累积式,
补丁 `scripts/patch_pi_cumulative_args.py`(npm 重装后需重跑)。
计划书: `plans/completed/0806-[pi作为harness]stage2-pi原生工具拉通.md`,
run log: `runs/2026-08-06_pi_stage2_agentic_dev.md`。

**核心发现**: S1/S2 高度互补 — S2-only 对 69 题,S1-only 对 72 题,**union oracle 71.7%**。
工具赢在关键瞬间类(Basketball +11pp),输在运动感知类(Relative_Velocity -28pp)。

**Case Viewer**: `scripts/pi_case_viewer.py`(Flask, 7875 端口,代理友好)+
`scripts/build_case_viewer.py`(数据包构建);S1/S2 对比 + Stage2 轨迹回放。

**Next**: 混合路由(运动类走 S1,瞬间类走 S2)冲 60%+。

## Key Results Summary

| Configuration | Accuracy | Samples |
|---------------|----------|---------|
| qwen3-vl-plus baseline | 50.6% | 403 |
| **qwen3-vl-plus via pi (Stage 1, 无工具)** | **54.6%** | 403 |
| qwen3-vl-plus + V4 tools | 55.6% | 403 |
| qwen3-vl-8b-thinking baseline | 50.6% | 403 |
| qwen3-vl-8b-thinking + V4 tools | 47.4% | 107 (partial) |
| qwen3-vl-8b-thinking + pi agentic (修复后) | **51.4%** | 403 |
| Best-of-both oracle (per-task) | 59.3% | 403 (estimated) |

两模型互补：8b-thinking 擅长预测类 (Soccer +23pp, Golf +12pp)，plus 擅长空间感知 (Passage +19pp, Ego +18pp)。

## History

### V4 Action Plan Pipeline (2026-08-02 ~ 08-03)

**架构**: Planner(JSON actions) → Action Executor(预建代码) → Hybrid Verify(VLM observe + tool evidence)

**核心组件**:
- `agent/coding_agent/action_executor.py` — 8 种动作映射到确定性 SDK 调用
- `agent/coding_agent/prompts/planner.py` — 模型选择 1-3 个动作的 JSON 计划
- `agent/coding_agent/pipeline.py` — 三路径: hybrid(VLM+tool) / vlm_observe_judge / vlm_fallback

**Pipeline 流程**:
1. Planner → 模型看帧+题目，输出 JSON 动作列表
2. Recipe 检查 → 内容匹配 recipe 则用 sandbox 执行
3. Action executor → 预建代码执行动作，无需 sandbox
4. Hybrid verify → VLM 先观察帧，再结合 tool 证据判断
5. Fallback → 工具全部失败时 VLM observe+judge

**全量 dev 结果 (403 samples): 55.6%**

| Source | Accuracy | Count | 说明 |
|--------|----------|-------|------|
| action_plan | 66% | 61 | 仅工具证据 (Vehicle_Movement, Relative_Velocity) |
| hybrid | 55% | 176 | VLM observe + tool 证据 |
| vlm_fallback | 57% | 80 | 工具失败 → VLM |
| vlm_observe_judge | 48% | 86 | 纯 VLM |

Per-task breakdown:
| Task | Accuracy | 主要路径 |
|------|----------|---------|
| Interaction_Direction | **82%** | vlm_fallback |
| Knot_Type | **75%** | vlm_observe_judge |
| Vehicle_Movement | **71%** | action_plan |
| Passage_Feasibility | **69%** | hybrid |
| Basketball_Shot | 65% | hybrid |
| Relative_Velocity | 64% | action_plan |
| Ego_Motion | 60% | hybrid |
| Rotation_Direction | 50% | vlm_fallback |
| Soccer_Shot | 49% | hybrid |
| Billiards_Shot | 48% | hybrid |
| Mikado_Dependency | 48% | vlm_observe_judge |
| Swimming_Race | 45% | hybrid/VLM |
| Golf_Shot | 44% | hybrid |
| Fall_Direction | 43% | vlm_fallback |
| Jenga_Stability | 40% | vlm_observe_judge |

### 关键发现

1. **模型能正确选择工具**: compensate_camera_motion → 速度类, estimate_camera_yaw → ego 运动, track_keypoints → 人体动作
2. **torch 不可用** → track_keypoints 总失败 → Fall_Direction/Rotation_Direction/Interaction_Direction 走 VLM fallback
3. **工具证据双刃剑**: 对 Vehicle_Movement (+21pp vs random) 帮助巨大, 对 Soccer_Shot/Golf_Shot 基本无用
4. **VLM "No" bias**: qwen3-vl-plus 对预测类问题（"是否进球"）强烈偏向"No"
5. **Hybrid > Tool-only > VLM-only**: 对大多数有工具证据的任务，hybrid verify (VLM+tool) 效果最好

### 版本对比
| Version | Accuracy | Architecture |
|---------|----------|-------------|
| V1 generic+recipe (task routing) | 51.4% | 硬编码 task 路由 |
| V2 observe+judge+recipe | **57.8%** | recipe + VLM fallback |
| V3 free-form codegen | ~25% code success | 模型写 Python |
| **V4 action plan (hybrid)** | **55.6%** | 模型选动作 → 预建代码 → VLM+tool verify |

### 瓶颈分析
- **模型能力上限**: qwen3-vl-plus 在纯视觉预测任务（shot prediction, stability）上约 50%
- **torch 不可用**: 人体姿态/关键点工具无法运行
- **VLM bias**: 预测类问题强烈偏向否定答案

## Active plans

- Phase 4 plan: 已完成核心实现

## Next recommended action

1. **安装 torch** 启用关键点跟踪 → Fall_Direction (+), Rotation_Direction (+)
2. **改进 VLM prompts** → 减少 "No" bias (但 CoT 测试显示效果不大)
3. **增加 recipe 覆盖** → 为 Ego_Motion, Basketball_Shot 写专用 recipe
4. **混合策略**: 用 V2 的 recipe 结果合并 V4 的 VLM 结果, 取每个 task 的最优
5. **换模型**: 测试 qwen3-vl-max 或其他更强 VLM

## Do not do

- 不在 private held-out set 上调参
- 未经确认不跑大规模 GPU 批量评测
- API keys 只存 `agent/llm_keys.local.json`（chmod 600）
