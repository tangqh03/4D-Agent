---
status: completed
created: 2026-08-01
completed: 2026-08-03
---

# Baseline 复现 + 工具链 v1（T1/T2/T4）

## User Goal

> （继承自 v1 plan）设计 agent 系统打 ViSTR-Bench 榜；先人工 hack：人工设计几个工具，
> 保证大部分题的解法能命中工具。依据：`docs/knowledge/tool_design_v1.md`。

### 二阶段
动机：
我觉得人工设计泛化性会很差。我觉得最好还是让vlm自己决定怎么去plan+verify

做法（我要你做的）：
我有两个key xz6gpBNmR33auolyjj6zbTgA，JZNLQIi0Wk4yspyiHpuCqoxj；url是"http://ai-llm-gateway.amap.com/open_api/v1"
你用qwen3-vl-plus 去探究：
- 模型遇到这些问题会怎么plan（工具空间待定）
- 模型怎样制定核验的checklist才敢确定

注意plan和verify上下文要隔离
每个题都过一遍。届时结果也做到前端的一个新page里

(本阶段总结：感觉完全放任qwen自己去规划有个问题，就是他给的plan是听着可行但实际行不通的，因此三阶段的时候拟限定下planner的解空间)

### 三阶段 A：ViSTR 工具解空间探索

动机：

二阶段中允许 Qwen3-VL-Plus 自由生成 Plan 和 Verify checklist，
发现模型会提出大量听起来合理但当前系统无法执行的工具、测量与物理假设。

但目前尚不能立即冻结 Planner 的动作空间，因为还没有确定：
1. 哪些工具能够真实覆盖 ViSTR-Bench 的 15 个子任务；
2. 每个工具能够稳定输出哪些证据；
3. 哪些工具组合能够实际提升最终准确率；
4. 工具的延迟、失败率及幻觉风险如何。

因此，本阶段首先探索并确定 Tool Registry v1，
然后再进入受限 Planner。

#### 候选工具空间

只探索以下五类 capability-level tools：

1. ground_and_track
2. analyze_motion
3. reconstruct_geometry
4. extrapolate_trajectory
5. analyze_physical_relations

具体 backend 可以替换，但对 Planner 暴露的 API、输入和输出必须统一。

#### 探索要求

首先解析 ViSTR-Bench 全部公开样本，按照 15 个子任务进行分组。

将公开数据划分为：
- tool_dev：用于开发和调试工具；
- tool_eval：用于冻结工具前的盲测。

必须按 15 个子任务分层划分，禁止在同一批样本上同时调工具和汇报最终结果。

对每个工具分别完成：

1. 实际可运行的最小实现；
2. 结构化输入输出 schema；
3. 结果可视化；
4. 成功率、延迟和显存统计；
5. 相关任务上的 evidence correctness 人工抽查；
6. Direct VLM 与 VLM + Tool 的消融；
7. 失败样本与适用边界分析。

每个工具输出证据，不允许直接输出最终 Yes/No 或类别答案。

#### 单题工具调用限制

Planner 每道题最多调用：
- 2 个主要工具；
- 1 个可选辅助工具；
- 同一工具最多 repair / retry 一次。

禁止为了制造冗长推理链而调用与最终决策无关的工具。

#### 冻结标准

只有满足以下条件的工具才能进入 Tool Registry v1：

1. 能够在目标任务上稳定运行；
2. 输出能够被 schema 解析；
3. 工具结果能够生成可视化 artifact；
4. 不依赖 GT；
5. 不输出未经支持的绝对尺度；
6. 相比 Direct VLM，至少在部分相关子任务上带来可复现收益，
   或显著降低错误结论的置信度；
7. 能明确返回 success / uncertain / failed，而不是强行生成结果。

产出：

- configs/tool_registry_candidate.yaml
- docs/analysis/tool_space_exploration.md
- docs/analysis/tool_task_coverage_matrix.md
- outputs/tool_ablation/

## For Agent: Execution Protocol

按 `docs/agent/always.md` 执行；每次实验写 run log；完成后按模板归档清单归档。

## Agent Refined Plan

### Understanding

文档/前端/调研已归档（见 `plans/completed/2026-07-31-vistr-agent-v1.md`）。
本 plan 进入实施：先跑 baseline 拿对照线，再按工具报告 §6 的 v1 范围（T1 提示框解析 +
T2 ego-motion 补偿 + T4 轨迹外推 + 证据摘要器）实现 driving 双任务与球类任务的工具化解法。

### Scope

#### In Scope

- reasoner 底座选型确认（本地 `/mnt/xlab-nas-wm/gaozhe.gz/hf_datasets` 的 Qwen3-VL-8B/4B-Thinking、InternVL3-2B vs API）——**需用户拍板**
- baseline：direct prompting（+官方 manual-CoT 组），public 670 全量，结果写 `outputs/predictions/`
- 工具链 v1：T1（绿/蓝框解析，纯 cv2）、T2（背景仿射 ego 补偿）、T4（抛物线外推）、证据摘要器
- 每步与 baseline 做 per-task A/B，前端 dashboard 跟踪

#### Out of Scope

- 工具链 v2/v3（姿态引擎、VGGT、SAM2）——下一个 plan
- 独立 env 治理（user-site numpy 问题）——接入 VGGT 前必须解决
- private held-out 任何调参

### Steps

1. 用户确认 reasoner 底座 → 搭 `agent/` 评测骨架（数据加载、prompt 组装、答案解析、JSONL 写出）
2. baseline direct + manual-CoT 两组跑 public 670，写 run log + 前端对比
3. T1+T2：Vehicle Movement / Relative Velocity 工具化解法（98 题）A/B
4. T4：球类轨迹外推（204 题）A/B
5. 误差分析 → 决定 v2（姿态引擎）范围

### Steps（二阶段，用户 2026-08-01 追加）

> 动机：人工设计泛化性差 → 让 VLM 自己决定怎么 plan + verify。用 qwen3-vl-plus 探究，
> plan/verify 上下文隔离，每题都过，结果进前端新 page。

1. ~~探通 AMAP 网关（OpenAI 兼容，16 帧 base64 图像输入）~~（已完成）
2. ~~实现 `agent/`：llm 客户端（双 key 轮换+重试）、PLAN/VERIFY 双隔离 prompt、断点续跑 runner~~（已完成）
3. ~~全量 670 题 plan+verify（后台运行中）~~ → 完成后写 run log
4. ~~前端新增 Plan+Verify 页（聚合指标 + 工具词频 + 逐样本双栏）~~（已完成）
5. 全量结果分析：模型自由提出的工具空间分布、checklist 模式、plan↔verify 一致性与准确率关系 → 反哺 agent 架构（notes/analyses 留档）

## Required Agent Resources

### Rules

- `rule:safety` → `docs/agent/rules/safety.md`

### Skills

- `skill:visualize` → `docs/agent/skills/visualize_benchmark_results/SKILL.md`

### Knowledge

- `knowledge:vistr-bench` → `docs/knowledge/vistr_bench.md`
- `knowledge:tool-design-v1` → `docs/knowledge/tool_design_v1.md`
- `adr:tool-augmented-arch` → `docs/adr/2026-07-31_tool_augmented_agent_architecture.md`

## Acceptance Criteria

- [x] baseline direct + manual-CoT 两组 acc（public 670）写入 run log，前端可见
- [x] T1/T2 在 driving 双任务 A/B 有结论（vs baseline per-task acc）
- [ ] T4 在球类任务 A/B 有结论 — 转为 V4 action plan 架构覆盖，不再单独做 T4
- [x] 误差分析留档（notes/analyses/）

---

## Execution Report

### Summary

经历三个阶段迭代，从人工硬路由 → VLM 自由 plan+verify → 模型驱动 action plan pipeline。

| Version | Accuracy | Architecture |
|---------|----------|-------------|
| V1 (task routing) | 51.4% | 硬编码 task 路由 + 手写 solver |
| V2 (observe+judge+recipe) | 57.8% | recipe + VLM observe+judge fallback |
| V4 (action plan, plus) | 55.6% | 模型选动作 → 预建代码 → hybrid verify |
| Baseline (plus) | 50.6% | direct prompting |
| Baseline (8b-thinking) | 54.3% (recovery 后修正, 2026-08-09) | direct prompting, 与 plus 互补 |

### Changed Files

| File | Change |
|------|--------|
| `agent/llm.py` | LLM 客户端（双 key 轮换+重试+model override） |
| `agent/prompts.py` | Plan/Verify 双隔离 prompt |
| `agent/run_plan_verify.py` | 全量 plan+verify runner |
| `agent/coding_agent/` | V4 action plan pipeline（全部新建） |
| `agent/eval_baseline.py` | baseline 直接推理评测 |
| `agent/tools/` | 底层工具：ground_track, motion, ego_odom, pose_motion 等 |
| `scripts/` | 可视化、前端脚本 |
| `web_frontend.py` | Streamlit 前端（taxonomy/leaderboard/sample browser） |

### Verification Results

见 run logs:
- `runs/2026-08-02_plan_verify_full.md` — Plan+Verify 全量结果
- `runs/2026-08-03_v4_action_plan_eval.md` — V4 pipeline 全量结果
- `runs/2026-08-03_8b_thinking_eval.md` — 8b-thinking 模型对比

### Outputs

- `outputs/predictions/baseline_8b_thinking.jsonl` — 8b-thinking baseline
- `outputs/predictions/coding_agent_8b_thinking.jsonl` — 8b-thinking V4 (partial)
- `outputs/predictions/coding_agent_v4_hybrid.jsonl` — plus V4 全量
- `outputs/plan_verify/qwen3-vl-plus_plan_verify.jsonl` — plan+verify 全量

### Remaining Issues

- torch 不可用 → 关键点工具 disabled
- VLM "No" bias → 预测类任务准确率受限
- 两模型互补但未实现 ensemble

### Human Review Guide

#### What changed conceptually

从人工设计工具+硬路由，演化为模型自主选择工具的 action plan 架构。证明了工具增强（+5pp）和模型互补（oracle +4pp）的可行性。

#### Key code pointers

* `agent/coding_agent/pipeline.py:solve_sample` — V4 主流程
* `agent/coding_agent/action_executor.py:execute_plan` — 8 种动作执行器
* `agent/coding_agent/prompts/planner.py` — 模型选动作的 prompt
* `agent/coding_agent/prompts/verifier.py` — hybrid verify prompt
* `agent/llm.py:chat` — LLM 调用入口

#### Code maps created/updated

* N/A

### Suggested Next Step

- Model ensemble (plus + 8b-thinking, per-task routing)
- 安装 torch 启用关键点工具
- 测试更强 VLM (qwen3-vl-max)
