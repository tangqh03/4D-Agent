# pi 扩展工具测试套件 + 实现检查（2026-08-08）

## 目标

给 pi 扩展工具（`agent/pi_ext/vistr_video_tools.ts` 5 个观察工具 +
`agent/pi_ext/evidence_closure.ts` silent ledger + submit_answer）写测试，
并检查实现是否存在问题。

## 方法

- 无框架：node:assert 迷你 runner + **jiti 加载真实扩展 TS 源码**
  （alias 配置与 pi 自身 loader 完全一致：typebox /
  @earendil-works/pi-coding-agent）
- fetch 打桩：mock gateway（caption/selection/checker 三个 chat 路由）+
  perception service（/ground、/annotate）——零 LLM/GPU 调用
- ffmpeg 真实生成 2s/320×240/10fps testsrc 测试视频 + 测试图片，
  工具 execute() 端到端真实跑 ffmpeg 抽帧
- Python 侧：`agent/tests/test_eval_pi_parse.py` 覆盖 eval 解析逻辑

## 命令与结果

```bash
node agent/pi_ext/tests/run.mjs
# 76/76 passed（helpers 33 + ledger 7 + submit_answer 12 + video_tools 24）

/opt/conda/bin/python agent/tests/test_eval_pi_parse.py
# 16/16 passed

/opt/conda/bin/python -m py_compile agent/eval_pi_agentic.py agent/tests/test_eval_pi_parse.py
# OK
```

测试加载路径 = pi loader 的 jiti 路径（同 alias），等价验证扩展仍可被 pi 加载。

## 实现检查结论

### 未发现问题的方面（测试确认正确）

- timeSubset/timeStrict/spaceSubset/spaceStrict 时空语义（含 EPS 边界、interval
  不 ⊂ discrete、unknown 短路、bbox tol 5%、帧尺寸不一致不判定）
- mapEvent 各工具映射（PERCEPTION/DERIVATION、interval/discrete/point、bbox）
- REFINES 关系计算（crop@5s refines sequence[0,10]；范围外/同刻不判定）
- submit_answer 全分支：zero-evidence / derivation-only / CLOSURE YES / NO /
  checker 500 或异常 graceful error_bypass / 乱回复按 gap 处理 /
  one-shot 第二次自动接受 / 无 PERCEPTION 时短路不发 VLM
- 5 个观察工具 execute：抽帧数量、时间戳区间/升序/钳制、crop 像素换算、
  bbox 钳制 [0,1000]、反向/过小 bbox 报错、semantic_crop 单候选跳过选择子调用、
  多候选 VLM 选择、垃圾回复回退首候选
- **eval 侧 `_repair_swallowed_tool_calls`** 能恢复嵌套 JSON、连续 remnant 调用，
  并把扩展工具写入 `tool_trace`（合成 `salvaged-*` id）；非 assistant 消息中的
  `toolCall` 不再计数
- `extract_answer` 对 `Clockwise` / `Counterclockwise` 等重叠选项优先精确匹配，
  不再被短选项 substring 误解析

### 本轮发现并修复的问题（按严重度）

| # | 问题 | 位置 | 严重度 | 修复 |
|---|------|------|--------|------|
| 1 | `read_video_sequence` start_s > end_s 时静默坍缩为单时刻的 n 帧全同 | vistr_video_tools.ts | 低 | 返回友好错误，避免伪造时序证据 |
| 2 | `semantic_crop` 视频缺 time_s 时抛原始 Error | vistr_video_tools.ts | 低 | 与 `read_crop` 统一为友好错误 |
| 3 | crop 越界时实际抽帧已 clamp，但 details/ledger 记录原始时间 | vistr_video_tools.ts | 中 | details、文本和 ledger 统一记录实际抽帧时间 |
| 4 | 空/失败观察 details={} 仍会进入 PERCEPTION ledger | evidence_closure.ts | 中 | 仅完整有效的帧/空间 details 才建 evidence |
| 5 | salvaged 调用只计数、不进 `tool_trace`；连续调用会被贪婪匹配吞掉 | eval_pi_agentic.py | 低 | JSON decoder 逐调用恢复并保留合成 trace id |
| 6 | `timeSubset` 对空 discrete `[]` 空真 | evidence_closure.ts | 很低 | 空 scope 不再视为 subset |
| 7 | `submit_answer` 已接受后可重复触发 checker | evidence_closure.ts | 很低 | 增加 terminal accepted 状态 |
| 8 | `extract_answer` 的 substring fallback 误伤重叠选项 | eval_pi_agentic.py | 中 | 精确匹配优先，屏蔽被长选项包含的短匹配 |

无 P0/P1（正确性/崩溃）问题。62.2% 的 90 题结果依赖的核心路径（账本、
REFINES、门控分支、抽帧/裁剪）全部通过测试。

## 变更文件

| 文件 | 变更 |
|------|------|
| `agent/pi_ext/tests/` | 新增：harness.mjs（jiti+mock API+fetch stub+ffmpeg fixture）、run.mjs、helpers/ledger/submit_answer/video_tools 四个 .test.mjs |
| `agent/tests/test_eval_pi_parse.py` | 新增：eval 解析 16 用例 |
| `agent/eval_pi_agentic.py` | 修复 remnant tool-call 恢复、assistant-role 过滤、重叠选项解析 |
| `agent/pi_ext/evidence_closure.ts` | 修复空/失败 evidence、空 scope、重复 checker；保留测试面导出 |
| `agent/pi_ext/vistr_video_tools.ts` | 修复反向区间/缺 timestamp/非法输入，details 记录实际 clamp 时间；保留测试面导出 |
| `docs/registry/scripts.md` | 注册两个测试入口 |

## 后续候选

- 测试挂进 CI/或 `scripts/` 一个聚合入口
