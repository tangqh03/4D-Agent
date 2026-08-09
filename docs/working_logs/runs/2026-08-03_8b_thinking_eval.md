---
date: 2026-08-03
experiment: qwen3-vl-8b-thinking model comparison
result: baseline 50.6%, V4 pipeline 47.4% (partial)
samples: 403 (baseline), 107 (V4 partial)
output:
  - outputs/predictions/baseline_8b_thinking.jsonl
  - outputs/predictions/coding_agent_8b_thinking.jsonl
---

# qwen3-vl-8b-thinking vs qwen3-vl-plus

## Purpose

测试 8b-thinking（reasoning 模型）在 ViSTR-Bench 上的表现，与 qwen3-vl-plus 对比。

## Results

### Baseline Direct Prompting (8b-thinking, 403 samples): 50.6%

> **更正（2026-08-09）**：此 50.6% 为 08-03 原始实测（max_tokens=4096，53 样本答案被截断；输出文件 `baseline_8b_thinking.jsonl` 已不在仓库）。08-07 vLLM 全量重跑 + recovery 重跑截断样本后，8b-thinking 公平直答为 **54.3% (219/403)**（`outputs/predictions/baseline_qwen3-vl-8b-thinking_vllm_dev_recovered_merged.jsonl`），下文"两模型总分相同"的结论不再成立。

| Task | 8b-thinking | plus (V4) | Delta |
|------|------------|-----------|-------|
| Soccer_Shot | **72%** | 49% | **+23pp** |
| Fall_Direction | **57%** | 43% | **+14pp** |
| Golf_Shot | **56%** | 44% | **+12pp** |
| Vehicle_Movement | 65% | **71%** | -6pp |
| Interaction_Direction | 71% | **82%** | -11pp |
| Relative_Velocity | 52% | **64%** | -12pp |
| Ego_Motion | 42% | **60%** | -18pp |
| Passage_Feasibility | 50% | **69%** | -19pp |
| Basketball_Shot | 41% | **65%** | -24pp |
| Knot_Type | 75% | 75% | 0 |
| Jenga_Stability | 37% | 40% | -3pp |
| Mikado_Dependency | 36% | 48% | -12pp |
| Rotation_Direction | 43% | 50% | -7pp |
| Swimming_Race | 45% | 45% | 0 |
| Billiards_Shot | 39% | 48% | -9pp |

### V4 Pipeline (8b-thinking, 107/403 partial): 47.4%

Stopped early — 76s/sample (vs 19s with plus), ETA was ~7hrs.

## Key Findings

1. **两模型总分相同** (baseline 50.6%)，但 task-level 互补性极强
2. **8b-thinking 擅长预测/物理推理**: Soccer_Shot, Golf_Shot, Fall_Direction
3. **plus 擅长精细空间感知**: Passage_Feasibility, Ego_Motion, Basketball_Shot
4. **V4 工具对 8b 帮助有限**: 模型弱 → plan 质量低 → 工具证据价值下降
5. **Best-of-both oracle: 59.3%** — 如果能按 task 类型 route 到最优模型

## Implications

- Model ensemble / task-aware routing 有 ~4pp 提升空间
- Thinking model 在 prediction 任务上的优势来自 reasoning，不依赖工具
- 工具 pipeline 效果依赖 base model 能力（plan 质量是瓶颈）
