---
status: active
date: 2026-08-09
scope: pi-harness
---

# ADR: S2.6 本地 checker 使用受约束裁决，缺失裁决不得等价于 NO

## Context

qwen3-vl-8b-thinking 即使关闭 thinking 仍会输出超长分析。修复前 41 行中的 40 次
checker 全部触及 2048-token 上限，12 次在写出 `CLOSURE` 前截断，并被错误当成 NO。

## Experiment

| 配置 | #31 真实 checker 输入 | 结果 |
|------|-----------------------|------|
| 普通 prompt，2048 tokens | 历史运行 | 截断，无裁决 |
| verdict-first prompt，4096 tokens | 定向 smoke | 连续两次 length，无裁决 |
| prompt + assistant prefill + constrained YES/NO | 在线探针/重跑 | 2-token 探针；smoke 首次 YES/stop |

## Decision

本地 vLLM checker 使用 `CLOSURE: ` assistant prefill、关闭 thinking，并以
`structured_outputs.choice=[YES,NO]` 约束输出。只有显式 NO 能拒绝提交；缺失裁决
重试一次后按 checker failure 放行。非 vLLM provider 保留 verdict-first prompt 和
4096-token 通用请求，不发送 vLLM 专用字段。

## Rationale

扩大输出预算不能保证裁决出现，只会增加延迟。受约束解码直接保证协议形状；fail-open
与既有 checker 服务故障策略一致，并消除了“解析失败伪装成证据缺口”的语义错误。

## Consequences

- 本地 checker 的 NO 分支使用通用 gap 文案，不再依赖模型自由生成的详细理由。
- tool details 必须保存 checker reply、finish reason 和 attempts，供全量审计。
- 主模型 64k context 与 checker 的输出协议是两个独立问题；不得用扩大总窗口代替约束。
