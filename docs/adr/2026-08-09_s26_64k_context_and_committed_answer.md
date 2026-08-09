---
status: active
date: 2026-08-09
scope: pi-harness
---

# ADR: S2.6 对齐 64k 上下文并以 committed answer 为无 FINAL 恢复源

## Context

旧 S2.6 服务窗口 40960，但 pi 每轮请求 32768 输出，输入预算仅 8192；127/403
无答案会话全部以同一 context 400 结束。旧 eval 又从 reasoning 最后出现的选项猜答案，
导致 #332 已 accepted Blue 却被关系短语末尾的 Green 覆盖。

## Experiment

| Configuration | Key Metric | Result |
|---------------|-----------|--------|
| 2×GPU, 40960 | 无 FINAL | 127/403，均为 context 400 |
| 4×GPU, 65536 定向 smoke | 原失败题完整性 | 7/7 完成，0 context 400/provider error |

## Decision

S2.6 本地服务使用 GPU 0–3 TP=4、65536 窗口；pi 同步
`contextWindow=65536`、`maxTokens=32768`、`reserveTokens=32768`。无合法 FINAL 时，
只使用最后一次 `submit_answer` 的 `accepted=true` 参数；没有成功提交则 `pred=null`。

## Rationale

该配置保留 32768 输出预算，同时把输入预算扩至 32768并在越界前压缩。工具结果中的
accepted 状态是显式提交事实；reasoning 是可撤销的 deliberation，不具备提交语义。

## Consequences

- 全量运行期间 pi 配置必须与 64k 服务同步，切换服务时按备份恢复。
- 输出新增 `answer_source/no_answer/termination`，下游应显式统计无答案。
- 非 S2.6 继续保留 reasoning fallback，避免改变既有 Stage 2 结果。
- closure 的 claim→answer 蕴含和时空覆盖不在本 ADR 内，另做实验。
