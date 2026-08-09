---
status: active
scope: pi-harness
code_paths:
  - agent/pi_ext/evidence_closure.ts
  - agent/pi_ext/evidence_ledger.ts
  - agent/eval_pi_agentic.py
entrypoints:
  - "VISTR_PI_EXTENSION=agent/pi_ext/vistr_video_tools.ts,agent/pi_ext/evidence_closure.ts python agent/eval_pi_agentic.py"
last_verified: 2026-08-09
owner: gaozhe
---

# Evidence Closure (S2.6→S2.7) — 证据账本 + 视觉闭合门控

## Purpose

在 pi agent loop 中记录所有观察操作的**来源元数据**（时间范围、空间区域、认知类型），
同时在内存中缓存观察图片（runtime evidence store）。
Agent 提交答案时，multimodal VLM checker 收到关键声明 + 相关证据的**实际图片**，
判断关键声明是否有直接视觉证据支撑。

S2.6 → S2.7 的核心升级：checker 从纯文本（只看元数据）升级为多模态（看实际图片），
CLOSURE YES rate 从 1.8% → 21%（pt1 冒烟），checker 回复从空洞的 "no content stated"
变为具体视觉描述（"ball above the rim, not passing through"）。

## Architecture

```mermaid
flowchart TD
    subgraph Silent Ledger（agent 不可见）
        A[tool_result hook] -->|mapEvent + 图片缓存| B[Evidence Entry]
        B --> C["ledger: Evidence[]<br/>metadata + images(内存)"]
    end

    D[Agent 完成分析] -->|submit_answer tool| E{Closure Gate}
    E -->|oneShotUsed=true| F[auto-accept<br/>第二次调用直接放行]
    E -->|ledger 为空| G[GAP_NO_EVIDENCE<br/>拒绝+提示重新观察]
    E -->|仅 DERIVATION| H[GAP_DERIVATION_ONLY<br/>拒绝+提示直接看帧]
    E -->|有 PERCEPTION| S[selectRelevantEvidence<br/>时间匹配+工具优先级<br/>最多 3 条目 / 4 张图]
    S --> I[Multimodal VLM Checker<br/>收到 metadata + 实际图片]
    I -->|CLOSURE: YES| J[接受答案<br/>返回 FINAL 指令]
    I -->|CLOSURE: NO| K[拒绝+返回 gap 描述<br/>oneShotUsed=true]
    I -->|调用失败| L[error_bypass<br/>优雅放行]

    G & H & K --> M[Agent 重新观察] -->|再次 submit_answer| F
```

## Evidence Entry 结构

```typescript
interface Evidence {
  id: string;           // "E1", "E2", ...
  source: string;       // 工具名: index_video / read_video_sequence / semantic_crop / ...
  agent_step: number;   // 第几个观察操作（agent 时间）
  world_time: WorldTime; // 观察覆盖的视频时间段
  space: Space;          // 观察覆盖的空间区域
  epistemic_type: "PERCEPTION" | "DERIVATION";
  relations: Array<{ type: "REFINES"; of: string }>;  // 时空严格子集 → REFINES 关系
  producer_metadata: Record<string, unknown>;          // 工具特定元数据
  images: ImageRef[];    // runtime-only 图片缓存（不持久化）
  text_snippet: string;  // 工具返回的首个文本块（截断 200 字符）
}

interface ImageRef {
  data: string;          // base64
  mimeType: string;
}
```

**认知类型二分**：
- `PERCEPTION` — agent 直接看了视频帧（read_video_sequence, read_multiframe, semantic_crop, read_crop, read(image)）
- `DERIVATION` — 只拿到文字描述（index_video 的 VLM caption 时间线）

## 工具 → Evidence 映射（mapEvent）

| 工具 | world_time | space | epistemic_type |
|------|-----------|-------|----------------|
| `index_video` | discrete（采样时刻列表） | global | DERIVATION |
| `read_video_sequence` | interval [min, max] | global | PERCEPTION |
| `read_multiframe` | discrete | global | PERCEPTION |
| `semantic_crop` | point（time_s） | bbox（crop_bbox） | PERCEPTION |
| `read_crop` | point | bbox（pixels） | PERCEPTION |
| `read`（图片路径） | unknown | unknown | PERCEPTION |

非观察工具（bash, submit_answer 等）→ `null`，不记录。

## Checker 输入格式（S2.7 multimodal）

Checker 收到两部分输入：

**1. 文本 prompt**（包含完整 ledger 元数据摘要）：
```
E1 | index_video | DERIVATION | time={0.00, 0.74, 1.48, ...}s | space=global
E2 | read_video_sequence | PERCEPTION | time=[0.00, 1.00]s | space=global (6 imgs)
E3 | semantic_crop | PERCEPTION | time={2.40}s | space=bbox[450,200,600,400] (2 imgs) [refines E2]
```

**2. 相关证据的实际图片**（最多 4 张，来自 `selectRelevantEvidence()` 筛选的 top-3 条目）：
```
[E3] semantic_crop @ {2.40}s:
[actual image]

[E2] read_video_sequence @ [0.00, 1.00]s:
[actual image]
```

Checker prompt（multimodal VLM call，temperature=0，max_tokens=150，timeout=60s）：
- 输入：question + proposed answer + key_claim + ledger summary + 实际图片
- 要求判断：key_claim 是否被**展示的图片**直接确认
- 输出：`CLOSURE: YES` 或 `CLOSURE: NO | <gap description>`

## 相关性筛选（selectRelevantEvidence）

从 ledger 中选出与 key_claim 最相关的 PERCEPTION 条目：

1. **时间匹配**：从 key_claim 提取时间戳（正则 `(\d+\.?\d*)\s*s`），与每条 evidence 的 world_time 计算距离/包含关系
2. **工具类型优先级**：semantic_crop(5) > read_crop(4) > read_multiframe(3) > read_video_sequence(2)
3. **REFINES 链加分**：细化观察（REFINES 父条目）+2
4. **图片数量预算**：最多 3 条目、4 张图（防止 checker 变成第二个完整 Video QA agent）

## S2.5 vs S2.6 差异

| | S2.5 (`evidence_ledger.ts`) | S2.6 (`evidence_closure.ts`) |
|---|---|---|
| Ledger | 同 | 同（共享 mapEvent 逻辑） |
| Context 注入 | **有** — `context` hook 注入 `<EVIDENCE_STATE>` dashboard | **无** — ledger 对 agent 不可见 |
| 注入模式 | tail（追加消息）/ anchor（改写首条 user msg） | N/A |
| 提交门控 | 无 | `submit_answer` 工具 + VLM checker |
| 效果 | 中性（54.4~56.7%） | 90题 62.2%，全量 51.9~54.6% |

## Eval 集成（eval_pi_agentic.py）

```
检测 EXTENSION 含 "evidence_closure" → has_submit=true
  ↓
PROMPT 使用 WITH_SUBMIT 变体: "调用 submit_answer 工具提交你的答案"
  ↓
设 VISTR_QUESTION 环境变量（checker 需要原始题目）
  ↓
stderr 解析 [evidence-closure] 行 → closure 字段写入结果 JSONL
```

## Code Pointers

| Symbol | Path | Role |
|--------|------|------|
| `evidenceClosure` | `agent/pi_ext/evidence_closure.ts:170` | extension 入口 |
| `mapEvent` | 同上 :105 | 工具结果 → Evidence 映射 |
| `selectRelevantEvidence` | 同上 :130 | 相关性筛选（时间+工具类型+图片预算） |
| `pi.on("tool_result")` | 同上 :176 | silent hook：记录证据 + 缓存图片 + 计算 REFINES |
| `pi.registerTool(submit_answer)` | 同上 :221 | 门控工具：相关性筛选 + multimodal closure check |
| `gatewayConfig` | 同上 :160 | VLM 网关配置（默认 amap-gateway / qwen3-vl-plus） |
| `timeSubset / spaceSubset` | 同上 :51/:72 | 时空子集判定（REFINES 关系基础） |
| `evidenceLedger` | `agent/pi_ext/evidence_ledger.ts:99` | S2.5 版本（含 context 注入） |
| `has_submit` | `agent/eval_pi_agentic.py:92` | 检测 closure extension，切换 prompt 变体 |

## Session 持久化

所有 ledger 事件通过 `pi.appendEntry("evidence-closure", ...)` 写入 pi session JSONL，
可用 `type=custom, customType=evidence-closure` 过滤查看：

```json
{"type":"custom","customType":"evidence-closure",
 "data":{"transition":"ADD","evidence":{"source":"semantic_crop",...}}}
{"type":"custom","customType":"evidence-closure",
 "data":{"transition":"CLOSURE_NO","answer":"Yes","key_claim":"...","checker_reply":"...","gap":"..."}}
```

transition 类型：`ADD` | `GAP_NO_EVIDENCE` | `GAP_DERIVATION_ONLY` | `CLOSURE_YES` | `CLOSURE_NO` | `ACCEPT_ONESHOT` | `CHECKER_ERROR`

## Gotchas

- Checker VLM 是 **multimodal 调用**（text + image_url），最多 4 张图片
- `VISTR_CAPTION_PROVIDER` / `VISTR_CAPTION_MODEL` 控制 checker 后端（默认同主 VLM）
- `oneShotUsed` 是 per-session 状态，每次 pi 调用重置
- submit_answer 的 checker 调用有 60s 超时（比 S2.6 的 30s 更长，因为要处理图片），超时/失败 → 优雅放行
- 评测脚本只捕获 stderr 中的 `[evidence-closure]` 行作为 closure 诊断
- 图片缓存在内存中（`ImageRef.data` 为 base64），session 结束后释放；`appendEntry` 只存 metadata + `image_count`
- `selectRelevantEvidence` 的时间戳提取依赖 key_claim 中的 `Ns` 格式（如 "2.5s"），如果 agent 不写时间则退化为工具类型 + 步数排序
