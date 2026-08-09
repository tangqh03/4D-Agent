# Handoff — tqh 分支合并到 main：给 zhe gao 的交接说明

- Date: 2026-08-09
- From: tqh (tangqh03)
- To: zhe gao (gaozhe.gz)
- Status: 已合并到 main（PR 关联见本文件末尾）

## 一句话总结

tqh 分支相对 main 的差异 = **vLLM 8b-thinking 评测管线（本地服务可选）+ Bug C 根治 + S2.6 bugfix 批次（64k 上下文、工具崩溃修复、committed-answer 恢复）+ case viewer 增强**。你**不需要本地部署 vLLM**：默认 provider 仍是 `amap-gateway`，所有 vLLM/GPU 相关代码都是**可选基础设施**，不配置就不生效。

## 你的环境合并没有风险，原因

| 改动类别 | 影响评估 |
|----------|----------|
| 新增文件（configs/、scripts/launch_vllm*.py、recover_*.py、evals.sh、analyze_pi_behavior.py、build_case_viewer_hf.py、tests/） | **零影响**——全部是独立脚本/配置，不 import 不到的地方不会执行 |
| `agent/llm.py` / `agent/eval_pi.py` / `agent/eval_pi_agentic.py` 修改 | 默认行为不变：provider 默认 `amap-gateway`，不设 `VISTR_PI_PROVIDER=vllm-local` 就走原有 API 网关 |
| `agent/pi_ext/vistr_video_tools.ts` / `evidence_closure.ts` | 只在 pi 启动时显式设置 `VISTR_PI_EXTENSION=...` 才加载；`gatewayConfig()` 优先读环境变量，不配则回落到既有 gateway 配置 |
| `scripts/build_case_viewer.py` 默认路径 | 默认指向 8b/s26 本地输出（不在仓库）。**已修**：S1/S2 文件缺失时与 S21-24 一样自动跳过，不再抛 FileNotFoundError（本轮新增，smoke 已验证 `cases: 0` 正常退出）。你要用自己的数据，用 `VISTR_BCV_S1/S2/SESS/OUT` 等环境变量覆盖 |
| `scripts/pi_case_viewer.py` `--data-dir` | 新增参数，默认值不变（`web/case_viewer/data`）；不传则行为同以前 |
| `.gitignore` | `web/case_viewer/data/` → `web/case_viewer/`：整个目录的新增未跟踪文件（含 84MB 的 `data_pt6/`）不再入库，避免大文件进 git。已跟踪文件不受影响 |
| `web/case_viewer/index.html` | 仅新增 thinking 块渲染等前端展示，无后端依赖 |
| docs/ 全部 | 纯文档 |

## 本批改动详情

### 1. vLLM 8b-thinking 评测管线（新，可选）
- `scripts/launch_vllm_qwen3_vl_8b_thinking.py` + `configs/vllm_qwen3_vl_8b_thinking*.json`：本地 vLLM 启动（qwen3-vl-8b-thinking，TP=2/TP=4，port 8001）。你不跑本地就不需要。
- `scripts/run_vistr_vllm_evals.sh`、`scripts/recover_missing_vllm_answers.py`：8b 批量评测与缺失答案恢复脚本。
- 本地跑才需要：`VISTR_PI_PROVIDER=vllm-local VISTR_PI_MODEL=qwen3-vl-8b-thinking`，vLLM 服务端需 `--enable-auto-tool-choice --tool-call-parser hermes`，以及 pi 累积式 args 补丁 `scripts/patch_pi_cumulative_args.py`。

### 2. Bug C 根治（8b-thinking × vLLM 特有，不影响 plus/gateway 路径）
- 根因：8b-thinking 模型多轮新回合开头输出裸 `{"name":...}</tool_call>`（漏开标签），工具调用被吞进 thinking。
- vLLM serving 层 `parse_delta` 补丁在**仓库外** `/workspace/vllm-src/vllm/parser/abstract_parser.py`（本仓库不携带）；`eval_pi_agentic.py` 的 `_repair_swallowed_tool_calls` 是 eval 侧兜底。
- 对 amap-gateway 路径无任何影响。

### 3. S2.6 bugfix 批次（核心收益）
- **工具崩溃修复**：`index_video`/`semantic_crop` 内部 VLM subcall 对 thinking 模型返回 `content=null` → 旧代码 `null.trim` 崩溃（dev403 中 333/403 case 含 655 次崩溃）。现解析 content 与 reasoning 分离、null 优雅失败、thinking 不作答案。
- **64k 上下文**：服务窗口 40960→65536（GPU0-3 TP=4 配置），pi 同步 `contextWindow=65536 / maxTokens=32768 / reserveTokens=32768`。修复 127/403 无答案全部死于 context 400 的问题。ADR: `docs/adr/2026-08-09_s26_64k_context_and_committed_answer.md`。
- **committed-answer 恢复**：无合法 FINAL 时只从最后一次 `submit_answer` 的 `accepted=true` 参数恢复；无成功提交则 `pred=null`，禁止用 reasoning 猜答案。新增 `answer_source/no_answer/termination` 字段。
- **closure checker 修复**：checker VLM 对 thinking 模型 `content=null` 触发 `null.trim()` TypeError → 静默 error_bypass；已修（`enable_thinking=false` + few-shot + null-safe），dev403 CHECKER_ERROR=0。
- **ledger 数据校验**：无效 times/box/frame 不再进证据账本；`caption_ok=false` 的失败 index 不再记为证据。
- 结果：S2.6 dev403 **52.9%**（213/403，+1.5pp vs 无 gate 51.4%）；工具 3304 次调用全部真实执行、0 error。

### 4. Case viewer 增强（本地工具，不影响你的数据）
- 两阶段轨迹匹配（toolCall-id 精确 395/403 + 模板级兜底）、思考块全量渲染、manifest 模式（HF 轨迹包）、多实例 `--data-dir`、环境变量覆盖各阶段路径。

### 5. 测试（零 LLM/GPU，可随时跑）
```bash
node agent/pi_ext/tests/run.mjs                    # 93/93 passed
/opt/conda/bin/python agent/tests/test_eval_pi_parse.py   # all passed
```

## 在你的环境如何正确合并

```bash
git checkout main && git pull origin main     # 先确保与远端同步
# PR 合并后即可,无需任何额外步骤。合并后验证:
git log --oneline -5                          # 应看到本批次提交
node agent/pi_ext/tests/run.mjs               # 可选:离线测试自检
```

合并本身是纯新增 + 小改，无 schema 变更、无数据迁移、无 API 断点。

## 已知限制/注意事项
- vLLM 8b 路径只在本机验证过（GPU 0-7，含 `/workspace/vllm-src` 的 serving patch）；你如要跑 8b，需要**自己部署 vLLM + 重打 parse_delta 补丁**（补丁内容见 `docs/working_logs/runs/2026-08-08_pi_8b_vllm_tool_call_bare_json_fix.md`，不在仓库内）。
- **新发现（未修复）**：closure checker 的 VLM subcall `max_tokens=2048` 对 8b 话痨回复普遍截断（35/37 截断，其中 8/37 在裁决行 CLOSURE: 写出前被切 → 有效 claim 被误拒一轮）。影响 64k dev403 全量运行，处理方案待定（候选：max_tokens 4096/8192、截断与 genuine NO 区分、few-shot 限制长度）。详见 `docs/notes/debug/tqh.md` §4.5。
- `build_case_viewer.py` 默认 S1/S2 路径指向本机 8b/s26 输出（gitignored，不随仓库分发）；你用 plus 数据请设 `VISTR_BCV_S1/S2` 或直接用 `build_case_viewer_hf.py` 打 HF 包。
- `docs/notes/debug/tqh.md` 是调试草稿（hypothesis），未经过评审，不视为结论。
- 预测输出都在 `outputs/`（gitignored），不在仓库里；PR 不含任何评测结果数据。

## 关联材料
- PR: https://github.com/HeShiLie/4D-Agent/pull/1（**tangqh03 只有 pull 权限，合并按钮在 HeShiLie/维护者侧**）
- 运行日志: `docs/working_logs/runs/2026-08-08_s26_8b_gpu01_dev403.md`、`2026-08-09_s26_bugfix_64k_smoke.md`、`2026-08-08_pi_ext_tools_tests.md`、`2026-08-09_pi_trajectory_tool_audit.md`
- 状态: `docs/working_logs/active.md`
