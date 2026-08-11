---
status: active
date: 2026-08-09
scope: pi-harness
---

# ADR: S2.6 closure 只声明 provenance 验证，并显式保留 unresolved 终态

## Context

S2.6 的旧 `submit_answer` 在 checker 首次 NO 后允许一次重观察，但第二次提交会自动接受；
因此“accepted”同时混合了 checker YES 和仍未验证的答案。qwen3-vl-8b-thinking 在
Basketball Outcome Prediction 上又会把截断后尚未发生的进球写成已观察事实。旧 schema
中的正向篮球示例、关系式 semantic_crop query 和固定 `Yes / No` 展示会进一步混淆来源。

checker 只接收文本 ledger，不看原始像素。它可以审计 claim 是否有直接观察 provenance，
不能可靠判断像素内容、关系真值或未来 outcome。把 checker NO 等价为答案错误同样不成立。

## Experiment

| 配置 | Key Metric | Result |
|------|------------|--------|
| 历史 S2.6 dev403 | 335 submit 的首次→最终准确 | 180→183，仅净增 3 题；118 重提仅 25 次翻转 |
| 历史 Basketball submit | Yes/claim/flip | 首次 Yes 33/35；35/35 声称已见 outcome；10 次重提 0 翻转 |
| 当前中断运行 | 47 行预测分布 | Yes 43 / No 2 / None 2；已在 47 行停止 |
| 反转选项 + cutoff prompt | 4 个原错题 | 展示 No/Yes 后仍全 Yes，1/4 |
| 加 localization-only warning | #1/#9 | checker 4 次 NO，终态均 verified=false；模型仍全 Yes |

## Decision

S2.6 closure 被定义为 provenance/epistemic gate，而不是答案真值 checker：

1. `submit_answer` 必须同时提交直接可见的 `key_claim` 和另一选项的
   `alternative_evidence`。
2. 第一次 NO 后必须新增观察并重新运行 checker；第二次仍 NO 以
   `unresolved_*/verified=false` 有界终止，不得标成已验证。
3. eval 只接受成功 submit 所承诺的答案；裸 FINAL 或与 accepted submit 不一致的 FINAL
   不得绕过 gate；首次接受后的重复 submit 也不得更换 committed answer。
4. Prediction prompt 明确 cutoff 和等先验；二元选项按样本 ID 确定性 counterbalance。
5. semantic_crop 仅承诺物体定位，query 和 score 不能作为动作、关系或 outcome 证据。
6. unresolved 不触发强制答案翻转，也不自动映射为 No。

## Rationale

该设计把“是否有可追溯观察”和“答案是否为真”分离。重新检查能消除旧 one-shot 的假闭环；
显式 unresolved 让全量统计可审计。counterbalance 排除固定位置诱导，但不改变语义标签。
不强制翻转是因为 checker 看不到像素，provenance 不足无法证明相反选项成立。

四题 smoke 证明 prompt 层约束不足以消除 8B 的 Basketball Yes 偏置，但也证明新 gate 会
一致地把相关 claim 标为未验证。诚实暴露模型缺陷优于通过后处理制造虚假的分数提升。

## Consequences

- `accepted=true` 不再等价于 `verified=true`；所有消费者必须读取
  `details.verified` 或汇总字段 `terminal_verified/terminal_closure`。
- `unresolved_after_retry` 和 `unresolved_no_new_evidence` 是有界运行终态，不是 closure 成功。
- 全量报告必须同时包含 accuracy、答案分布、answer flip、verified 和 unresolved 比例。
- 旧 47 行 bugfix2 输出包含旧自动放行语义，禁止续跑或与新实现合并。
- 当前 dev403 全量处于 HOLD；即使未来授权，也必须使用新输出从零测量。
- 该决策不修复模型的像素关系理解；若要提升答案质量，需要独立的视觉 verifier、tracking/
  trajectory 特征或模型层改进，而不是扩大 vLLM context 或把 unresolved 强制改成 No。
