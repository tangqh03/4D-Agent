---
status: active
scope: evaluation
last_verified: 2026-08-07
owner: gaozhe
---

# Run Log — pi 观察原语迭代(S2.1→S2.4b,90 题均匀子集)

- **Date**: 2026-08-07
- **Model**: qwen3-vl-plus(amap-gateway),主 agent 与 caption/selection subcall 同型号
- **子集**: `--per-task 6` = 90 题(15 任务 × 6,任务内等间距;用户约定默认抽样)
- **Extension**: `agent/pi_ext/vistr_video_tools.ts`(逐阶段扩充)
- **Outputs**: `outputs/predictions/pi_agentic_ext{,2,3,4b}_qwen_pt6_20260807.jsonl`

## 迭代与结果(同 90 题)

| 版本 | 新增原语 | Acc | 关键行为 |
|------|---------|-----|---------|
| S2 基线 | 无(原生 read/bash) | 50.0% | 87% 看图轮次单帧 |
| S2.1 | read_video_sequence + read_multiframe | 51.1% | 单帧率降至 14% |
| S2.2 | index_video(batch VLM caption 时间线,无题目上下文) | 51.1% | index→multiframe 组合率 66% |
| S2.3 | read_crop(normalized bbox 自回归) | 48.9% | 手写 ffmpeg crop 归零;但首发 miss ~28% |
| S2.4 | semantic_crop(GroundingDINO 服务) | 44.4%* | *prompt 清单漏列,仅 5 次调用,无效实验 |
| **S2.4b** | 同上(清单修复) | **56.7%** | semantic_crop 118 次(39% 题),Mikado 6/6 |

参照:SpatialClaw 同子集 53.3%(全量 56.6%);S1 纯问答 52.2%。

| 口径 | Claw | S2.2 | **S2.4b** |
|------|------|------|-----------|
| 全 90 | 53.3 | 51.1 | **56.7** |
| 去 Soccer (84) | 53.6 | 51.2 | **57.1** |
| 去 4 射门 (66) | 53.0 | 57.6 | **57.6** |

## Grounding 对比(5 探针,scripts/grounding_probe.py)

| | read_crop(自回归 bbox) | semantic_crop |
|---|---|---|
| 平均调用 | 3.2(最差 7) | **1.4**(4/5 首发命中) |
| 平均耗时 | 40s | 28s |

## 基础设施

- `scripts/perception_service.py`:常驻 model-pool(:7876),GroundingDINO GPU 常驻
  (MI308X,权重 `hf_datasets/grounding-dino-base`);extension 零权重加载,纯 HTTP
- semantic_crop 链路:target(英文)→ top-6 候选 → 编号图 → 隔离 VLM 选 ID(不见题目)
  → 15% 固定 margin 原图裁剪 → receipt + 高清 crop

## 关键教训

1. **user prompt 工具清单不完整会压制新工具**(S2.4→S2.4b 差 12pp):pi 本身会把
   extension 工具 promptSnippet 动态入 system prompt,但任务文本里的枚举权重更高。
   规则:要么不列,要列列全(详见 knowledge/pi_harness.md §3)
2. GroundingDINO 词表仅英文(中文 → [UNK]),已在工具 description 约束
3. 观察原语已四件套齐备;顽固弱项 Fall/RelVel/Vehicle(各 1/6)是运动感知,
   grounding 无解,候选:光流/跟踪后端进 model pool

## Next

- oracle(S2.1∪2.2∪2.3)=76.7% → 观察策略选择/融合仍是最大空间
- model pool 下一住户:光流或 SAM2 跟踪(运动感知三弱项)
