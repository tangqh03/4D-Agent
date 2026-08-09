# Run log — Bug C remnant 根因调查(2026-08-08 凌晨)

## 结论(一句话)

Bug C 的 remnant(`{json}</tool_call>` 在 thinking 块)是 **8b-thinking 模型自身的输出行为**(多轮工具上下文下在 thinking 里直接输出工具 JSON 但不配对 `<tool_call>` opening tag),**不是 vLLM parser 吞 tag**——token 流级证据成立。vLLM parser 无可靠修复点,eval 侧 post-hoc recovery 是当前唯一缓解,实时 interception(方案 B)是根治路径。

## 背景

- 交接文档(2026-08-07)假设:模型正确输出 `<tool_call>{json}</tool_call>`,vLLM qwen3 reasoning parser 把 opening tag 吞掉(implicit reasoning end),JSON+closing 残留 thinking。
- 本次调查用 token 流级证据裁决该假设。

## 证据链

### 1. vLLM API 输出字段名是 `reasoning`,不是 `reasoning_content`

- 原始 SSE:`{"delta":{"reasoning":"好的"}}`
- 此前所有脚本(含我的早期重放)读 `reasoning_content` → 恒空 → 误判"模型不思考/remnant 不存在"
- 修正后重放 20 次样本 36:reasoning 987-23327 字符,模型每次都在思考

### 2. 单轮请求(第一轮)从未产生 remnant

- 样本 36 正确 prompt 重放 20 次、并发 2 请求 ×5 轮、样本 49 并发:全部 remnant=False
- 第一轮模型路径:`</think>` → `<tool_call>{json}</tool_call>` → hermes 正确解析(tc 正常)

### 3. remnant 几乎只在多轮(round 2+)出现

- 694 个 pi session 扫描:254 个有 remnant(37%),round 分布:round1=1, round2=96, round3=38, round4=22, round5+ 分散到 round27
- 典型结构:第一轮 assistant(thinking+text+toolCall) → toolResult → 第二轮 assistant thinking 含 remnant

### 4. remnant 形态 = 孤立 closing tag,无 opening tag

- pi session 中 remnant:`{"name": "bash", "arguments": {"command": "ffmpeg ..."}}\n</tool_call>`
- logprobs token 流:模型输出 `</tool_call>`(151658)但**从不输出 `<tool_call>`(151657)**——8 次真实捕获请求重放中 151657 出现 0 次,151658 出现 2 次(在 tool-call 阶段,被 hermes 处理)
- parser debug 日志(3001802, 25k 行):失败样本 `is_end via <tool_call>` 0 次,`</tool_call>` 在 [no-end branch] 出现 14 次——opening tag 从未到达 parser
- **结论:opening tag 不存在于引擎输出,不是 parser 吞的**

### 5. vLLM parser 对 151658 的处理正确

- qwen3 parser 的 reasoning-end 检测:`</think>`(151668)或 `<tool_call>`(151657);151658 不是 end 标记 → JSON+closing 作为 reasoning 忠实输出
- 这是**正确行为**:parser 无法区分"thinking 里讨论 JSON"与"thinking 里实际调用工具"

### 6. 触发条件 = 工具调用行为,非 server 版本

- 08-07 11 UTC(19:00 本地)49 个 session:toolCalls=0(模型不用工具)→ 0% remnant
- 14 UTC(22:00)后 remnant 率 28-49%:正是 Bug A(PATH ffprobe)/Bug B(prompt 诚实)修复后模型开始调用工具的时期
- 时间线曾误导为"parser patch 引入",实为工具调用引入

### 7. 当前 server(clean 版, 3410825)重放真实捕获多轮请求 12 次仍 0 remnant

- 真实 7-message(4 工具结果)/ 4-message(1 工具结果)请求原样重放:全干净
- remnant 触发是 stochastic 的(temperature=1.0, top_k=20),真实完整 agentic 会话多轮累积后出现率 ~37%

## 复现尝试汇总(全失败)

| 实验 | 次数 | remnant |
|------|------|---------|
| 样本 36 单轮(读错字段) | 20 | 0(假阴性) |
| 样本 36 单轮(修正字段) | 20 | 0 |
| 并发 2 请求 | 10 | 0 |
| 4-message 重建第二轮 | 5+8 | 0 |
| 真实捕获 7-message 第三轮 | 8+10 | 0 |
| 真实捕获 4-message 第二轮 + 6-message 第三轮 | 8+8 | 0 |
| 真实捕获批量(clean server) | 6+6 | 0 |
| logprobs token 流检查 | 12 | 151658 ×2 无 151657 |

## 对修复方案的影响

| 方案 | 状态 | 评价 |
|------|------|------|
| vLLM parser 源码修复(23:17 版:阶段切换标志) | 保留 | 对第一轮 opening tag 处理有效;对第二轮 remnant **无效**(模型不输出 opening,parser 无从处理) |
| eval 侧 post-hoc `_repair_swallowed_tool_calls` | 保留 | 能从 thinking 提取 JSON 计入 tool_calls,**但无法让 pi 真正执行工具** → 模型幻觉状态无法修复 |
| 方案 B:实时 interception(检测 remnant → 注入 tool_result → 继续 agentic 循环) | 建议 | 根治路径:被吞工具真正执行,模型上下文正确 |
| 降低 temperature(1.0 → 0.7) | 可选 | 减少随机输出格式错误,但不消除 |

## 附带发现

1. `/root/.pi/agent/models.json` vllm-local baseUrl 为 8002(调试代理残留,**曾 8001**)。8002 是另一个会话的请求捕获代理(23:31 启动,/tmp/proxy_log.py,记录到 /tmp/pi_request_dump.jsonl)。**勿改**(其他会话在用)。
2. eval 默认 provider 是 amap-gateway;跑本地 vLLM 需 `VISTR_PI_PROVIDER=vllm-local VISTR_PI_MODEL=qwen3-vl-8b-thinking`。
3. vLLM 环境:`envs/311`(vllm 0.23.1.dev0, 源码 /workspace/vllm-src);启动经 `scripts/launch_vllm_qwen3_vl_8b_thinking.py`。

## 关键文件

| 文件 | 说明 |
|------|------|
| `/tmp/pi_request_dump.jsonl` | 8002 代理捕获的真实请求(含多轮) |
| `/tmp/replay_sample36_20260807.py` 等 | 重放脚本(字段名修正版) |
| `/tmp/vllm_launch_20260808_clean.log` | 当前 server 日志(clean 版,无 parser debug) |
| `/root/.pi/agent/sessions/` | pi session 全量(694 个,254 个含 remnant) |
