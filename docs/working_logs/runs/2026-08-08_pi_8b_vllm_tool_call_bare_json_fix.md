# Bug C 根治:vLLM 吞 tool_call — 裸 JSON 开标签缺失修复

- Date: 2026-08-08
- Scope: vLLM serving 层 parser 修复(接续 handoff `docs/working_logs/handoffs/2026-08-07_pi_stage2_8b_vllm_tool_call_bug_fix.md`)
- Model: `/data/Qwen3-VL-8B-Thinking/` via local vLLM TP=8 port 8001
- vLLM config: `configs/vllm_qwen3_vl_8b_thinking_recovery_8gpu.json`
- Serving session: `tmux vllm`(运行中,日志 `/tmp/vllm_launch_20260808_clean.log`)

## 背景

handoff 中 Bug C(vLLM reasoning parser 间歇性吞 `<tool_call>`)"~14% 样本"的根因
此前被认为与 qwen3 parser 的 `</think>`/`<tool_call>` 标签检测有关,上一轮已在
`vllm/reasoning/qwen3_reasoning_parser.py` 加了 string-level 兜底(单元测试 9/9),
但真实环境冒烟测试 8/8 FAIL——兜底从未被触发。

## 根因定位(2026-08-08 凌晨)

通过 HTTP 代理捕获 pi 真实请求 + VLLM_PARSER_DEBUG 逐 delta 日志,确认:

1. **pi 请求不带 `tool_choice` 字段**(key 缺失),max_tokens=32768,4 个工具
   (read/bash/edit/write),temperature 由 vLLM 默认(1.0,非确定性——解释间歇性)。
2. **失败现场(日志 line 1469 一带)**:`</think>`(151668)正常触发 reasoning end,
   **但该 delta 已是上一个请求的结尾**(中间有 HTTP 200 边界)。下一个请求的
   **第一个 delta 就是裸 `{"name": ...}` JSON**(`prev_tail=''`),没有 `<tool_call>`
   开标签(151657 全程出现 0 次),没有 reasoning,也没有 `</think>`。
3. 该请求处于 reasoning 相位(模板在 prompt 末尾放 `<think>`),流里没有任何
   结束信号 → 整个 JSON 工具调用(含闭标签 `</tool_call>` 151658)全部被当作
   reasoning 吞掉。全量日志中共 **14+ 个请求**以裸 JSON 开场。
4. **不是 parser 的标签检测 bug,是模型采样问题**:Qwen3.5 模型在工具调用请求的
   新回合开头,偶尔直接输出 JSON 体(可能受 temperature 1.0 采样影响),漏掉了
   `<tool_call>` 开标签。JSON 本体 + `</tool_call>` 闭标签是完整、可解析的。

## 修复

**`/workspace/vllm-src/vllm/parser/abstract_parser.py`** `DelegatingParser.parse_delta`:

reasoning 相位入口新增裸 JSON 检测:当请求配了 tools(`request.tools` 非空)、
`tool_choice` 为 auto/None、流处于请求开头(`previous_text` 为空)、且 delta 以
`{"` 开头时——立即结束 reasoning 相位,并把 `self._tool_parser.tool_call_start_token`
(hermes 的 `<tool_call>`)**重建到 content 流前面**,让 hermes tool parser 正常解析。

门控刻意收窄,避免误伤:
- 仅请求开头的裸 JSON(模型无 reasoning 直接开场)
- 仅带 tools 且 tool_choice∈{auto, None} 的请求
- mid-stream 的 `{"name":...}`(推理正文中出现)不触发

另外保留了上一轮的 string-level 兜底(qwen3 parser,针对"标签跨 delta 边界/
拆成普通 token"场景),二者互补。

## 验证

### 单元测试 `/tmp/test_bare_json_fix.py` — 6/6 PASS

| 场景 | 结果 |
|------|------|
| T1 生产失败序列:裸 JSON 开场 → 工具调用被提取(name=bash, 完整 arguments) | PASS |
| T2 首个 delta 只有 `{"` 再续 JSON 体 | PASS |
| T3 正常 reasoning → `</think>` → content(回归) | PASS |
| T4 无 tools 请求 → 不重建 | PASS |
| T5 tool_choice=none → 不重建 | PASS |
| T6 推理中途出现 `{"name":...}` → 不重建 | PASS |

### 冒烟测试(修复后,带 debug 重启)

修复前基线(正确覆盖 local vLLM):4 轮中 **2 轮 FAIL(tc=1, swallowed=1)**——parser bug 稳定复现。

修复后 6/6 PASS,真实流量中重建事件 5+ 次触发:

```
tc=2 swallowed=0 PASS
tc=2 swallowed=0 PASS
tc=2 swallowed=0 PASS
tc=7 swallowed=0 PASS
tc=2 swallowed=0 PASS
tc=3 swallowed=0 PASS
```

### 最终验证(干净重启,无 VLLM_PARSER_DEBUG)

4/4 PASS,两轮合计 **10/10 PASS、swallowed 恒为 0**:

```
tc=13 swallowed=0 PASS
tc=3 swallowed=0 PASS
tc=8 swallowed=0 PASS
tc=6 swallowed=0 PASS
```

### 冒烟测试正确姿势

```bash
# 必须带覆盖变量,否则走默认的 amap-gateway/qwen3-vl-plus 远程模型!
VISTR_PI_PROVIDER=vllm-local VISTR_PI_MODEL=qwen3-vl-8b-thinking \
  /opt/conda/bin/python /tmp/pi_smoke_test_20260807.py
```

## 环境收尾

- `~/.pi/agent/models.json` baseUrl 已从代理 8002 恢复为 `http://127.0.0.1:8001/v1`
  (备份 `/tmp/models.json.bak`)
- 代理 `/tmp/proxy_log.py`(8002)已停止
- vLLM 以无 debug 状态运行(tmux `vllm` session)

## 遗留

- 模型有时"裸 JSON 开场但 JSON 永远不闭合"(直接跑飞成中文)——这类无法在
  parser 层恢复(无闭标签),属于模型质量问题,仍由 eval 侧
  `_repair_swallowed_tool_calls` post-hoc 打捞兜底
- 全量 dev 403 未重跑:修复前 50.4%(203/403,~14% early_term),修复预期 +0.5pp
  级别提升;如需确认可重跑全量(需确认,约 2-4 小时)
