---
status: active
scope: evaluation
last_verified: 2026-08-07
owner: gaozhe
---

# Run Log — pi Stage 2 (原生工具) × 本地 vLLM qwen3-vl-8b-thinking 全量 dev

- **Date**: 2026-08-07
- **Script**: `agent/eval_pi_agentic.py --split dev --workers 4 --resume --timeout 600`
- **Harness**: pi v0.84.0，默认工具集(bash/read/edit/write/grep/find/ls)，workspace = 临时目录 + video.mp4 拷贝
- **Model**: `qwen3-vl-8b-thinking` via 本地 vLLM（TP=8，GPU 0-7，port 8001，`--enable-auto-tool-choice --tool-call-parser hermes`）
- **Output**: `outputs/predictions/pi_agentic_qwen3-vl-8b-thinking_vllm_dev.jsonl`
- **Log**: `outputs/logs/pi_agentic_8b_dev_20260807.log`

## Setup / 前置修复

1. **vLLM tool-choice 未开启**：pi 发 `tool_choice: auto` 被 400 拒绝
   (`"auto" tool choice requires --enable-auto-tool-choice and --tool-call-parser`)。
   → `scripts/launch_vllm_qwen3_vl_8b_thinking.py` + `configs/vllm_qwen3_vl_8b_thinking_recovery_8gpu.json`
   新增 `enable_auto_tool_choice` / `tool_call_parser` 支持。
2. **parser 选型**：`qwen3_xml` 只认 `<function>/<parameter>` XML，而 Qwen3-VL 模板输出
   `<tool_call>{JSON}</tool_call>`（读 tokenizer_config 确认）→ 实测 hermes parser
   （`<tool_call>(.*?)</tool_call>` 正则 + JSON 解析）正确抽取，改 `tool_call_parser: hermes`。
3. **pi 累积式 args 补丁**重打：`/opt/conda/bin/python scripts/patch_pi_cumulative_args.py`
   （npm 重装后曾丢失，必须重跑）。

## 第一轮冒烟暴露的问题（2026-08-07 下午修复）

4. **思考未落盘 + 大量样本无最终答案**：原 `eval_pi_agentic.py` 用 text 模式（`-p` 不带 `--mode json`），
   只存 `raw_answer`(后 800 字符)。思考模型多轮工具循环时，部分会话在输出预算内结束、
   没产出最终文本 → pred=None 且思考丢失（~30% 样本）。
   - **修复 A**：`--mode json` + `_parse_pi_json`（同 c9f5f63 stage1 的做法），按 assistant role 过滤，
     落盘 `reasoning`（全轮 thinking 拼接）/ `final_answer` / `tool_calls` 计数；`extract_answer` 强化
     提取（FINAL: 行 → 文本内选项 → 思考尾部兜底）。
   - **修复 B**：`~/.pi/agent/models.json` `maxTokens` 16384 → **32768**（用户要求 32k）。
   - **修复 C**：`configs/...recovery_8gpu.json` `max_model_len` 61440 → **131072**、`max_num_seqs` 16 → 8
     （KV 估算 131072×8≈19.3GB/GPU，0.9 util=22GB 内可容；实测 17.2GB/GPU 余量充足）。重启 vLLM。
   - 冒烟 3 样本：reasoning 24/47/113KB 落盘 ✓，tool_calls 8/14/17 ✓，无 pred=None ✓。

## 全量 dev（完成）

### Run 1（broken tool env → 废弃）
403 样本，4 workers，输出 `pi_agentic_qwen3-vl-8b-thinking_vllm_dev.jsonl`。
**结果：67/403 后停止**。根因：pi 子进程 PATH 无 ffmpeg/ffprobe，prompt 却宣称"已装"→模型疯狂找二进制（61/62 样本受污染）。

### 修复
1. **PATH 修复**：`agent_env()` prepend `/opt/conda/bin`(cv2 4.13) + `/opt/conda/envs/spatialagent/bin`(ffmpeg 8.1.2)
2. **Prompt 修正**：诚实描述工具可用性，禁止 `which`/`whereis`/`find /` 找二进制
3. **Recovery 逻辑**：`_repair_swallowed_tool_calls()` 从 thinking 块中恢复被 vLLM reasoning_parser 吞掉的 `<tool_call>` 片段
4. **启动自检**：`_self_check()` 确保工具链/pi 补丁可用再启动

### Run 2（修复后）
403 样本，4 workers，PID 142765，耗时 3h36m。
**初步结果**：201/397 = 50.6%（agentic），6 个 error。cmd_not_found 仅 8/403（2% vs 之前 98%）。

Buggy 样本：65 个（57 early_term + 8 cmd_not_found，含 overlap）。tc_avg 2.9。
Recovery 净效果接近 0（对答案无增益——模型 reasoning 已有答案表达）。

### Run 3（buggy 重跑）
65 样本，3 workers，耗时 39min，`pi_agentic_8b_vllm_dev_buggy_rerun.jsonl`。
**结果**：30/65 = 46.2%（44.6%→46.2%，+2 净 gain，14↑12↓）。tc_avg 8.2（工具恢复正常多轮）。

### 最终合并：50.4%（203/403）

| Task | Acc |
|------|-----|
| Knot_Type | 75% |
| Interaction_Direction | 71% |
| Swimming_Race | 67% |
| Passage_Feasibility | 60% |
| Ego_Motion | 56% |
| Golf_Shot | 56% |
| Soccer_Shot | 55% |
| Fall_Direction | 50% |
| Mikado_Dependency | 48% |
| Rotation_Direction | 47% |
| Basketball_Shot | 46% |
| Vehicle_Movement | 44% |
| Relative_Velocity | 44% |
| Billiards_Shot | 43% |
| Jenga_Stability | 40% |

## 对比目标

- Stage 2 + qwen3-vl-plus (AMAP): 53.8% (217/403)
- Stage 2 + 8b-thinking (vLLM): **50.4%** (203/403) ← 本次
- Baseline + 8b-thinking (vLLM): 47.6% (192/403, raw 4096-token trace；recovery 重跑截断样本后 54.3%)
- Stage 1 + 8b-thinking (vLLM): 46.9% (189/403, raw trace；recovery 后 54.6%)
- Stage 1 + pi (8b-thinking): 54.6% (220/403, recovery merged 已确认)

**结论**：8b-thinking 工具模式 50.4%，高于 raw baseline 47.6%（+2.8pp），但低于截断修复后的公平 baseline 54.3%（-3.9pp）；比 S1 无工具（raw 46.9%）高 3.5pp。
工具收益确认存在但受模型能力限制；plus 版比 8b 高 3.4pp（53.8% vs 50.4%）。
已知间歇性问题：vLLM qwen3 reasoning_parser 偶尔吞 tool_call（~14% 样本），已有 recovery 处理。
