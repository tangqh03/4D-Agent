---
status: active
last_updated: 2026-08-10
---

# ViSTR-Agent — Active Work State

## Current Focus: S2.8 — Context-preserving crop + 去掉证据账本 (2026-08-10)

基于 S2.4b 的纯观察原语路线（全量 56.3%/56.5%，速度最快 91s/sample），
重构 crop 工具为 **context-preserving image/video spatial-temporal zoom**：

**核心改动**（`vistr_video_tools.ts`）：
1. `contextualROI()` — grounding bbox → 60% expansion + 25% minimum extent → context-preserving crop
2. `cropVideoSegment()` — ffmpeg 视频段空间裁剪 → zoomed mp4（写入 workspace，agent 可递归观察）
3. `temporalUnion()` — 多时间点 grounding bbox 求并集 → stable ROI
4. `semantic_crop` / `read_crop` 新增 `start_s` + `end_s` 参数 → 视频段 zoom（stable ROI，不逐帧跟踪）
5. 去掉 evidence_closure（S2.6/S2.7 全量未提升总分，增加 60% 耗时）

**S2.8 结果**：90-subset 56.7%（与 S2.4b 持平），25s/sample（3.6× 快于 S2.6/2.7）。
**✅ dev403 全量已完成（2026-08-11 00:49）：224/403 = 55.6%**（8b dev403 历史最佳），
11117s（27.6s/sample）。输出 `outputs/predictions/pi_s28_qwen3-vl-8b-thinking_vllm_gpu0-3_96k_dev403_20260810.jsonl`。
唯一硬门禁缺口 #191（stop=length 过度思考、0 工具，`pred=null` 未补写，非 infra）。
详见 `docs/working_logs/runs/2026-08-10_s28_8b_96k_dev403.md`。

**qwen3-vl-8b-thinking × vLLM 适配完成（2026-08-10）**：复用 GPU 0–3、TP=4、
96k context 的本地 vLLM `:8001` 和 GPU 6 perception `:7876`。修正无 closure 时
prompt 仍要求不存在的 `submit_answer`、视频段末帧 preview 精确 seek，以及时段参数
静默混用；S2.8 的 contextual ROI / temporal union / stable ROI 核心算法不变。
真实视频段探针通过（semantic crop → H.264 zoomed MP4 → 递归读取 3 帧）；public dev
IDs 1/114/229 smoke 3/3 完成，14/14 工具真实执行、0 tool/provider error、0 no-answer、
0 submit_answer，准确率 1/3（非门禁）。全量 dev403 已交接 Claude Code，见
`docs/working_logs/handoffs/2026-08-10_s28_qwen3_vl_8b_96k_dev403_claude.md`。

**全量对比（403 题）**：
| 版本 | Micro | Macro | Avg time | 说明 |
|------|-------|-------|----------|------|
| S2.4b | 56.3% | **56.5%** | 91s | 纯观察原语，无 gate |
| S2.6 r1 | 54.6% | 54.4% | 148s | text-only closure checker |
| S2.6 r2 | 51.9% | 53.6% | — | 同上，二次跑 |
| S2.7 | 53.6% | 55.1% | 153s | multimodal closure checker |
| **S2.8（8b，96k）** | **55.6%** | — | 27.6s | context crop，无 gate |

结论：closure gate 在全量上未提升总分。S2.8 context-preserving crop 在 8b 全量
（55.6%）上超过 S2.4b 全量的 plus 路线（56.3%，不同模型）之外，成为 8b 全量最优，
且速度最快（27.6s/sample）。

**Pi extensions**(`agent/pi_ext/`)：
- `vistr_video_tools.ts` — 5 观察工具 + S2.8 context-preserving crop
- `evidence_closure.ts` — S2.6/S2.7 closure gate（当前不加载）
- `evidence_ledger.ts` — S2.5 evidence board（当前不加载）

## Current Focus: S2.6 × qwen3-vl-8b-thinking dev403 全量（2026-08-08，GPU 0/1 TP=2 本地 vLLM :8001）

按交接文档执行：本地 vLLM qwen3-vl-8b-thinking（TP=2，GPU 0/1，port 8001，
configs/vllm_qwen3_vl_8b_thinking_gpu01_s26.json）+ 本地 perception GroundingDINO-base
（GPU 6，:7876，`GDINO_PATH` 环境变量覆盖指向本地 HF 缓存，lazy 模式，S2.6 设计一致）。

**本次修复**（`agent/pi_ext/evidence_closure.ts`）：
1. checker VLM 调用对 thinking 模型返回 `content=null`（思考耗尽预算）→ 旧代码
   `null.trim()` TypeError → error_bypass 静默禁用 closure gate。修复：
   `chat_template_kwargs.enable_thinking=false` + `max_tokens=2048` + null-safe `?? ""`。
2. 8b 模型回复自由文本不按 `CLOSURE:` 格式 → 加 few-shot 示例 + 填空式结尾
   （"CLOSURE: " 引导补全），实测 checker 输出 `CLOSURE: YES/NO` 行并可正确判
   PERCEPTION/DERIVATION 覆盖。

**验证进度**：回归 77/77（node）+ 16/16（python）通过；单样本 smoke（86s/67s/56s）
无卡死，工具 7/7 与 4/4 真实执行 0 错误，closure 分支覆盖（confirmed / gap→
re-observe→oneshot accept）；两题 smoke 通过；per-task 1（15 题）门禁通过
（7/15=46.7%，工具 15/15 全绿，CHECKER_ERROR=0）。

**✅ dev 403 全量已完成（2026-08-08 21:30 启动）**：
**52.9% (213/403)**，对比参考 51.4% (207/403, 8b pi agentic 无 gate) **+1.5pp**；
0 error / 0 超时（max 657s）；3304 次工具调用全部真实执行（tools_executed==
tool_calls 403/403，tool_errors=0，salvaged=0）；submit 触发 335/403=83.1%
（490 次调用）；closure 分支 CLOSURE_YES 185 / CLOSURE_NO 145 /
ACCEPT_ONESHOT 117（gap 中 80.7% 回去 re-observe）/ ACCEPT_ALREADY 37 /
GAP_NO_EVIDENCE 1 / GAP_DERIVATION_ONLY 1，**CHECKER_ERROR=0（无 error_bypass）**。
输出 `outputs/predictions/pi_s26_qwen3-vl-8b-thinking_vllm_gpu01_dev403_20260808.jsonl`。
详见 run log `runs/2026-08-08_s26_8b_gpu01_dev403.md`。

**服务已停止（2026-08-09 07:0x）**：vLLM（pid 3390154，EXIT 0）与 perception
（pid 3365315，EXIT 143）均已优雅 SIGTERM；GPU 0-7 全部回到 15 MiB 空闲基线，
端口 8001/7876 已释放。复现需重新启动（配置在 `configs/vllm_qwen3_vl_8b_thinking_gpu01_s26.json`，
perception 用 `GDINO_PATH` 指向本地 HF 缓存）。

## Current Focus: S2.6 Evidence Closure — answer-time visual verification

pi (v0.84.0) harness + extension 路线持续推进。S2.6 在 S2.4b 观察原语基础上增加
**evidence closure gate**: silent ledger 后台记录观察来源,agent 提交答案时检查关键事实
是否有直接视觉证据闭合,如有缺口允许一次 re-observation。

## Current Focus: Bug C 根治 + 8b-thinking × vLLM 全量重跑(2026-08-08)

**根因**：8b-thinking 在多轮工具上下文的新回合**开头**直接输出裸
`{"name":...}</tool_call>` 而漏掉 `<tool_call>` 开标签（151657 出现 0 次，
stochastic，触发率 37%）——是模型采样行为，reasoning parser 无解。

**修复**：vLLM serving 层 `parse_delta` 检测"配 tools 的请求 + 流开头 + `{"`" →
重建 `<tool_call>` 开标签进 content 流。单元测试 15/15，冒烟 **10/10 PASS、
swallowed 恒为 0**（修复前 2/4 FAIL）。eval 侧 `_repair_swallowed_tool_calls`
保留作兜底。详见 `runs/2026-08-08_pi_8b_vllm_tool_call_bare_json_fix.md` +
handoff（status: resolved）。

**vLLM 状态**：tmux `vllm` 中 clean 版运行中（pid 3410825，envs/311，port 8001，
健康，**含修复**）。`~/.pi/agent/models.json` baseUrl 已恢复 8001。

**全量 dev 403 重跑（修复后）→ 51.4% (207/403)**，修复前 50.4%，**+1.0pp**；
吞工具样本（调用但未执行）**0**（修复前 ~14%），3590/3590 次调用全部真实执行，
8 个 600s 超时（基线同类 6 个）。输出
`outputs/predictions/pi_agentic_qwen3-vl-8b-thinking_vllm_dev_fix.jsonl`
（含轨迹字段），run log: `runs/2026-08-08_pi_8b_vllm_full_dev_rerun_after_fix.md`。

**工具轨迹落盘 + 执行校验**：`eval_pi_agentic.py` 输出 `tool_trace`（name +
arguments 即 bash command 全文）、`tool_results`（isError + content，read 图片
以 data_bytes 计防爆量）、`tools_executed`（匹配到执行结果的调用数，Bug C 度量）、
`tool_errors`。校验工具 `/tmp/check_tool_execution.py`（按 toolCallId 配对）。
验证：回放真实事件流 11/11 执行 0 error；live 冒烟 4/4 执行 0 error。

**扩展工具测试套件（2026-08-08）**：`agent/pi_ext/tests/run.mjs`（76/76 passed：
helpers 33 + ledger 7 + submit_answer 12 + video_tools 24，jiti 加载真实源码 +
fetch 打桩 + ffmpeg 真实测试视频，零 LLM/GPU）+ `agent/tests/test_eval_pi_parse.py`
（16/16）。已修复：失败/空观察误入 PERCEPTION ledger、crop 越界时间 provenance
错误、反向时间片段、semantic_crop 缺 timestamp、重复 checker、连续 swallowed
tool-call 丢轨迹，以及 `Clockwise`/`Counterclockwise` 选项误解析。详见
`runs/2026-08-08_pi_ext_tools_tests.md`。两扩展文件保留行为中性的测试面导出。

**Stage 2 × 本地 vLLM 8b-thinking**：`eval_pi_agentic.py` + provider `vllm-local`
（默认 amap-gateway，跑本地需 `VISTR_PI_PROVIDER=vllm-local
VISTR_PI_MODEL=qwen3-vl-8b-thinking`）。vLLM 需 `--enable-auto-tool-choice
--tool-call-parser hermes`；pi 累积式 args 补丁需重打：
`/opt/conda/bin/python scripts/patch_pi_cumulative_args.py`。

**合并说明（2026-08-08，第二轮）**：tqh(Bug C 修复 + 轨迹落盘线) × main(观察原语
S2.1-S2.4b + S2.5 证据账本 + **S2.6 evidence closure**)已合入 tqh。`eval_pi_agentic.py`
同时支持:JSON 轨迹落盘(默认)+ extension 观察原语 + evidence_closure 提交门控
(`VISTR_PI_EXTENSION=vistr_video_tools,evidence_closure` 时启用 submit_answer 流程)。

**S2.6 结果**: 90 题均匀子集 **62.2%** (S2.4b: 56.7%, +5.5pp; SpatialClaw: 56.6%)

**Stage progression**:
- S2.1–S2.4b: 观察原语(how to observe) → 56.7%
- S2.5: evidence board 注入(改变模型推理心态,中性结果) → 54.4~56.7%
- **S2.6: evidence closure gate(when to stop reasoning and re-observe) → 62.2%**

**Pi extensions**(`agent/pi_ext/`):
- `vistr_video_tools.ts` — 5 观察工具(index/sequence/multiframe/crop/semantic_crop)
- `evidence_closure.ts` — S2.6: silent ledger + `submit_answer` 工具 + VLM closure checker
- `evidence_ledger.ts` — S2.5: context 注入 evidence board(当前不加载)

**基础设施**: `scripts/perception_service.py` — 常驻 perception model-pool(:7876,
GroundingDINO GPU 常驻 MI308X);启动:
`nohup .../star/bin/python -u scripts/perception_service.py --port 7876 --eager &`

**评测约定**: 默认 `--per-task 6`(90 题);全量仅用户明确要求。

**Next 候选**:
1. ~~S2.6 full-split eval (403 samples) 确认总体提升~~ ✅ 52.9% (+1.5pp vs 51.4% 无 gate)
2. 改进 re-observation guidance (告诉 agent 具体看哪个时间段；gap 后 28/145 未 re-observe)
3. 运动感知弱项(Fall/RelVel):光流/跟踪后端进 model pool（8b 全量上 Passage 25% / RelVel 28% 最弱）
4. opus + 全套原语 + closure

**Claude Code 交接（2026-08-08）**：已生成
`docs/working_logs/handoffs/2026-08-08_s26_gpu01_qwen3_vl_8b_dev403.md`，内容覆盖
GPU 0/1、TP=2 的 vLLM 部署，现有 8 卡服务的安全切换门禁，主 agent 与 S2.6
辅助 VLM 全部走 `vllm-local`，smoke → per-task 1 → dev 403 分阶段测试，结果完整性
校验、失败恢复以及本轮 bug 修复清单。本 agent 只完成交接文档，没有启动服务或执行
本次 GPU 评测；Claude Code 按文档执行并写 run log。

## Key Results Summary

| Configuration | Accuracy | Samples | Avg time |
|---------------|----------|---------|----------|
| qwen3-vl-plus baseline | 50.6% | 403 | — |
| qwen3-vl-plus via pi S1(纯问答) | 54.6% | 403 | — |
| qwen3-vl-plus + V4 tools | 55.6% | 403 | — |
| SpatialClaw | 56.6% | 403 | — |
| claude-opus-4-6 via pi S1 | 57.1% | 403 | — |
| **pi S2.4b 全量(纯观察原语)** | **56.3% micro / 56.5% macro** | **403** | **91s** |
| pi S2.6 evidence closure 全量 r1 | 54.6% / 54.4% | 403 | 148s |
| pi S2.6 evidence closure 全量 r2 | 51.9% / 53.6% | 403 | — |
| pi S2.7 visual closure 全量 | 53.6% / 55.1% | 403 | 153s |
| pi S2.8 context crop (90题) | 56.7% | 90 | 25s |
| qwen3-vl-8b-thinking baseline (vLLM) | 54.3% | 403 | — |
| qwen3-vl-8b-thinking + S2.6 closure gate | 52.9% | 403 | — |

两模型互补：8b-thinking 擅长预测类 (Soccer +23pp, Golf +12pp)，plus 擅长空间感知 (Passage +19pp, Ego +18pp)。

## History

### V4 Action Plan Pipeline (2026-08-02 ~ 08-03)

**架构**: Planner(JSON actions) → Action Executor(预建代码) → Hybrid Verify(VLM observe + tool evidence)

**核心组件**:
- `agent/coding_agent/action_executor.py` — 8 种动作映射到确定性 SDK 调用
- `agent/coding_agent/prompts/planner.py` — 模型选择 1-3 个动作的 JSON 计划
- `agent/coding_agent/pipeline.py` — 三路径: hybrid(VLM+tool) / vlm_observe_judge / vlm_fallback

**Pipeline 流程**:
1. Planner → 模型看帧+题目，输出 JSON 动作列表
2. Recipe 检查 → 内容匹配 recipe 则用 sandbox 执行
3. Action executor → 预建代码执行动作，无需 sandbox
4. Hybrid verify → VLM 先观察帧，再结合 tool 证据判断
5. Fallback → 工具全部失败时 VLM observe+judge

**全量 dev 结果 (403 samples): 55.6%**

| Source | Accuracy | Count | 说明 |
|--------|----------|-------|------|
| action_plan | 66% | 61 | 仅工具证据 (Vehicle_Movement, Relative_Velocity) |
| hybrid | 55% | 176 | VLM observe + tool 证据 |
| vlm_fallback | 57% | 80 | 工具失败 → VLM |
| vlm_observe_judge | 48% | 86 | 纯 VLM |

Per-task breakdown:
| Task | Accuracy | 主要路径 |
|------|----------|---------|
| Interaction_Direction | **82%** | vlm_fallback |
| Knot_Type | **75%** | vlm_observe_judge |
| Vehicle_Movement | **71%** | action_plan |
| Passage_Feasibility | **69%** | hybrid |
| Basketball_Shot | 65% | hybrid |
| Relative_Velocity | 64% | action_plan |
| Ego_Motion | 60% | hybrid |
| Rotation_Direction | 50% | vlm_fallback |
| Soccer_Shot | 49% | hybrid |
| Billiards_Shot | 48% | hybrid |
| Mikado_Dependency | 48% | vlm_observe_judge |
| Swimming_Race | 45% | hybrid/VLM |
| Golf_Shot | 44% | hybrid |
| Fall_Direction | 43% | vlm_fallback |
| Jenga_Stability | 40% | vlm_observe_judge |

### 关键发现

1. **模型能正确选择工具**: compensate_camera_motion → 速度类, estimate_camera_yaw → ego 运动, track_keypoints → 人体动作
2. **torch 不可用** → track_keypoints 总失败 → Fall_Direction/Rotation_Direction/Interaction_Direction 走 VLM fallback
3. **工具证据双刃剑**: 对 Vehicle_Movement (+21pp vs random) 帮助巨大, 对 Soccer_Shot/Golf_Shot 基本无用
4. **VLM "No" bias**: qwen3-vl-plus 对预测类问题（"是否进球"）强烈偏向"No"
5. **Hybrid > Tool-only > VLM-only**: 对大多数有工具证据的任务，hybrid verify (VLM+tool) 效果最好

### 版本对比
| Version | Accuracy | Architecture |
|---------|----------|-------------|
| V1 generic+recipe (task routing) | 51.4% | 硬编码 task 路由 |
| V2 observe+judge+recipe | **57.8%** | recipe + VLM fallback |
| V3 free-form codegen | ~25% code success | 模型写 Python |
| **V4 action plan (hybrid)** | **55.6%** | 模型选动作 → 预建代码 → VLM+tool verify |

### 瓶颈分析
- **模型能力上限**: qwen3-vl-plus 在纯视觉预测任务（shot prediction, stability）上约 50%
- **torch 不可用**: 人体姿态/关键点工具无法运行
- **VLM bias**: 预测类问题强烈偏向否定答案

## Active plans

- Phase 4 plan: 已完成核心实现

## Next recommended action

1. **安装 torch** 启用关键点跟踪 → Fall_Direction (+), Rotation_Direction (+)
2. **改进 VLM prompts** → 减少 "No" bias (但 CoT 测试显示效果不大)
3. **增加 recipe 覆盖** → 为 Ego_Motion, Basketball_Shot 写专用 recipe
4. **混合策略**: 用 V2 的 recipe 结果合并 V4 的 VLM 结果, 取每个 task 的最优
5. **换模型**: 测试 qwen3-vl-max 或其他更强 VLM

## Do not do

- 不在 private held-out set 上调参
- 未经确认不跑大规模 GPU 批量评测
- API keys 只存 `agent/llm_keys.local.json`（chmod 600）

## pi Case Viewer 部署(2026-08-09)

- 启动:`/opt/conda/envs/spatialagent/bin/python -u scripts/pi_case_viewer.py --port 7875`(本机无 `python3.10.13` env,`/opt/conda/bin/python` 缺 flask;用 `spatialagent` env),后台运行,日志 `/tmp/pi_case_viewer.log`
- 数据:`scripts/build_case_viewer.py`(S1/S2 路径改为 8B vllm dev 文件;S21–S24 文件缺失,自动跳过)
- **两阶段轨迹匹配**(v2):阶段 1 用 **toolCall id 精确匹配**(vllm 每次调用 id 全局唯一,预测行 `tool_trace` 与 session 共享)→ **395/403 精确对应**,0 冲突(3590 个 id 全验证 question 一致);阶段 2 仅对 8 个 `src=error`(pi 退出,无 tool_trace)行做模板级兜底并前端标注(黄色警告条)
- 覆盖:403/403 case 有轨迹回放(395 精确 + 8 模板级兜底);教训:ViSTR 题目文本模板化(403 id / 74 唯一文本),不能按文本匹配
- Smoke test: 构建 `cases: 403 (403 with trajectory)`,API `/api/cases` `/api/case_detail` `/api/img` 均 200
- 待办:下次重跑 eval 时给 pi session 注入视频标识(如 cwd 名→case id 映射),实现精确匹配
- 轨迹工具审计:见 runs/2026-08-09_pi_trajectory_tool_audit.md(ffprobe 混用 3 次、专用视频工具 0 调用待核实扩展加载、虚构工具名 66 次)
- viewer 双实例:7875 = s26 run(web/case_viewer/data);7877 = HF 下载的 qwen_pt6 轨迹包(outputs/hf_export/,manifest 精确匹配 403/403,build 用 VISTR_BCV_S1/S2/SESS/MANIFEST/OUT env,viewer 用 --data-dir;pi_case_viewer.py 新增 --data-dir,build_case_viewer.py 新增 manifest 模式)

### HF 轨迹数据集回灌 + 独立 viewer(2026-08-09)

- 下载 `MihailSlutsky/vistr-pi-trajectories`(qwen3-vl-plus 的 S1/S2 轨迹,公开无 gating)到
  `outputs/hf_export/`:predictions_stage{1,2}.jsonl + stage{1,2}_trajectories.tar.gz(stage2 1.37GB,
  内含 agent 看过的帧 base64)→ 解包 `outputs/hf_export/sessions/`(自包含,不动 `~/.pi/agent/sessions`)
- 构建:`scripts/build_case_viewer_hf.py`(新增)——复用 build_case_viewer 辅助函数,但用 tar 内
  **manifest.json 精确匹配**(上传的 stage2 predictions 无 tool_trace,无法 toolCall-id 匹配),
  403/403 全部精确对应;输出同 schema 的 `web/case_viewer/data/`(8b 版备份在
  `/tmp/case_viewer_data_8b_backup`)
- viewer 起在 **7877**(7875 已被 8b viewer 占用,7876 留给 perception):`nohup spatialagent python -u scripts/pi_case_viewer.py --port 7877`
- Smoke:API `/api/cases`(403) `/api/case_detail` `/api/img` `/api/video` 全 200

### viewer 思考渲染(2026-08-09 追加)

- `build_case_viewer.py::parse_session` 现保留 thinking 事件(`{"t":"think","text":前1000字符,"chars":全长}`,MAX_THINK=1000);`pi_case_viewer.py` + `web/case_viewer/index.html` 渲染为斜体蓝块 + "💭 思考 (N 字符)" 标签,轨迹统计行加"段思考"
- 当前 `web/case_viewer/data/` 为 8b 版数据包(含思考,395/403 精确);7875/7877 均已重启加载。切回 plus 版: `spatialagent python scripts/build_case_viewer_hf.py` + 重启 viewer

### viewer 切换 s26 数据包 + s26 工具崩溃审计(2026-08-09 追加)

- 7875/7877 数据包切到 **s26**(dev403,403/403 toolCall-id 精确匹配;dev_fix+ext 版备份 `/tmp/case_viewer_data_devfix_backup`,116M)
- `build_case_viewer.py` 各档路径支持 `VISTR_BCV_S1/S2/S21..S24` 环境变量覆盖,默认 S2 = s26 dev403;S21–24 预测文件已不在仓库,重建时自动跳过
- 重启 7875/7877 后验证:1307 显示 s26 轨迹(pred=Left ✓),817 显示 s26 工具链(4×semantic_crop 崩溃)
- **s26 工具崩溃**:index_video `null.trim` 241 次 + semantic_crop `null.match` 414 次(全量 session);dev403 中 **333/403 case(83%)** 含 ≥1 次崩溃(622 次)。根因:vistr_video_tools.ts 内 captionTimeline(L120)/selectCandidate(L167)对 gateway VLM 返回的 `content: null` 无空值保护——thinking 模型输出只有思考块时 content=null;selectCandidate 的 max_tokens=8 对 thinking 模型结构性饿死(qwen3 模板强制 `<think>` 前缀)。详见 notes/debug/tqh.md §4
- closure gate:132 case 首次 submit 被拒后重试;盲点 = 不校验时间覆盖(#817 改写措辞即过)
