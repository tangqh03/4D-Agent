---
status: active
scope: pi-harness
code_paths:
  - agent/pi_ext/vistr_video_tools.ts
  - scripts/perception_service.py
  - agent/eval_pi_agentic.py
entrypoints:
  - "pi -p -e agent/pi_ext/vistr_video_tools.ts --provider amap-gateway --model qwen3-vl-plus \"...\""
  - "VISTR_PI_EXTENSION=... python agent/eval_pi_agentic.py --per-task 6 --workers 4"
  - "python scripts/perception_service.py --port 7876 --eager"
last_verified: 2026-08-07
owner: gaozhe
---

# pi 观察原语栈(extension + perception service)

## Purpose

为 pi harness 提供 task-agnostic 的视频时空观察原语(时间连续/离散证据/空间放大/语义定位),
只改善 observation affordance,不含任务路由或领域推理。不处理:采样策略决策、答案验证。

## Flow Diagram

```mermaid
flowchart TD
    A[主 VLM in pi agent loop] -->|toolCall| B{观察原语}
    B --> C["index_video<br/>均匀采样→batch VLM caption<br/>(无题目上下文)→文本时间线"]
    B --> D["read_video_sequence<br/>时间片段均匀抽帧,多图相邻回注"]
    B --> E["read_multiframe<br/>指定时刻联查(证据帧)"]
    B --> F["read_crop<br/>normalized bbox [0,1000]→原图裁剪"]
    B --> G["semantic_crop<br/>英文 target 描述"]
    G -->|HTTP /ground| H["perception_service :7876<br/>GroundingDINO GPU 常驻"]
    H -->|top-6 候选+编号标注图| G
    G -->|隔离 VLM subcall 选 ID<br/>只见候选图+target| I[网关]
    G -->|15% margin ffmpeg 裁剪| J["receipt(带框全图)+高清 crop 回注"]
    C & D & E & F & J --> A
```

## Core Pseudocode

```text
semantic_crop(path, target, time_s?):
    frame = 原始分辨率帧 (视频则 ffmpeg -ss)
    cands = POST /ground {image, target, topk:6, annotate:true}
    id    = len(cands)==1 ? cands[0] : VLM("哪个编号匹配 target?", 标注图)   # 不见题目
    box   = cands[id].bbox 外扩 15%(工具级常量,禁按任务调)
    return [receipt(/annotate 画选中框), crop(原图 ffmpeg)]

perception_service:
    启动/首调加载 GroundingDINO → 常驻 GPU;/health /ground /annotate
    registry dict 可挂 SAM2/DA3/VGGT(未部署)
```

## Code Pointers

| Symbol | Path | Role |
|--------|------|------|
| `vistrVideoTools` | `agent/pi_ext/vistr_video_tools.ts` | extension 入口,注册 5 工具 |
| `framesContent` | 同上 | 多帧+时间戳标签相邻回注(时序保持的核心) |
| `captionTimeline` | 同上 | index_video 的 batch caption 调用(硬约束:无题目) |
| `selectCandidate` | 同上 | semantic_crop 的隔离选择 subcall |
| `ground()` | `scripts/perception_service.py` | GroundingDINO 推理 + 编号标注图 |
| `EXTRA_TOOLS_NOTE` | `agent/eval_pi_agentic.py` | user prompt 工具清单(**必须列全**,见 pi_harness.md §3 教训) |

## Gotchas

- 网关流式 tool-call args 为累积式:pi-ai 需先打补丁 `scripts/patch_pi_cumulative_args.py`(npm 重装后重跑)
- GroundingDINO 文本仅英文(中文→[UNK])
- t=duration 抽帧为空 → 全部时间参数经 `clampT(dur-0.1)`
- perception 服务需先起(:7876),extension 只走 HTTP,禁止加载权重
