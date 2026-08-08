---
status: active
scope: general
last_verified: 2026-08-08
owner: gaozhe
---

# Output Registry

Index of all output directories and artifacts produced by this project.

## Format

```markdown
### Output Name
**Path**: `path/to/outputs/`
**Produced by**: Which script generates this
**Format**: File types and structure
**Notes**: Retention policy, dependencies, etc.
```

---

### Prediction results
**Path**: `outputs/predictions/`
**Produced by**: agent 评测管线（规划中）；mock 数据由 `visualize_results.py --demo` 生成
**Format**: JSONL，每行一个样本：
  `{id, task, dimension, question, options, gt, pred, correct, reasoning, evidence, video, video_relpath}`
**Notes**: 命名约定 `<model>_<config>_<date>.jsonl`（如 `gpt54_direct_0731.jsonl`）；每次实验必须在 `docs/working_logs/runs/` 有对应 run log

### Plan+Verify results（二阶段探究）
**Path**: `outputs/plan_verify/`
**Produced by**: `agent/run_plan_verify.py`
**Format**: JSONL，每行 `{id, task, gt, options, video, plan:{plan_text,answer,confidence,correct,raw}, verify:{checklist,self_check,answer,confidence,correct,raw}, agree, elapsed_s}`
**Notes**: 前端 Plan+Verify 页直接读取；断点续跑按 id 去重

### Visualization outputs
**Path**: `data/visualizations/`
**Produced by**: `visualize_results.py`（经 `scripts/visualize.sh`）
**Format**: `overview_dashboard.png`（leaderboard/任务热力图/错误分布）+ `samples/<id>_replay.mp4`（样本回放）
**Notes**: mp4 为 ffmpeg libx264 编码；样本回放用于 case 分析，可定期清理

### Coding Agent V4 results
**Path**: `outputs/predictions/coding_agent_v4_hybrid.jsonl`
**Produced by**: `agent/coding_agent/eval_coding_agent.py`
**Format**: JSONL，每行 `{id, task, gt, pred, correct, src, question, options, video, dimension, evidence, code, analysis_spec, elapsed_s, error}`
**Notes**: qwen3-vl-plus, V4 action plan pipeline, 403 samples, 55.6%

### 8b-thinking baseline
**Path**: `outputs/predictions/baseline_8b_thinking.jsonl`
**Produced by**: `agent/eval_baseline.py`
**Format**: JSONL，每行 `{id, task, gt, pred, correct, src, question, options, raw_answer, elapsed_s, model}`
**Notes**: qwen3-vl-8b-thinking, direct prompting, 403 samples, 50.6%

### 8b-thinking V4 pipeline (partial)
**Path**: `outputs/predictions/coding_agent_8b_thinking.jsonl`
**Produced by**: `agent/coding_agent/eval_coding_agent.py`
**Format**: 同 Coding Agent V4 results
**Notes**: qwen3-vl-8b-thinking, 107/403 samples (partial), 47.4%

### Task posters
**Path**: `web/posters/`
**Produced by**: `scripts/gen_task_posters.py`
**Format**: 15 张 480×270 JPG（每任务一帧代表帧）
**Notes**: taxonomy 页用；benchmark 数据更新后需重新生成

### pi harness Stage 1 dev results
**Path**: `outputs/predictions/pi_qwen3-vl-plus_dev_20260806.jsonl`
**Produced by**: `agent/eval_pi.py`
**Format**: JSONL，每行 `{id, task, gt, pred, correct, src, question, options, video, dimension, raw_answer, elapsed_s, model}`
**Notes**: qwen3-vl-plus via pi v0.84.0（print 模式,无工具）, 403 samples, **54.6%**; run log `docs/working_logs/runs/2026-08-06_pi_stage1_dev.md`; 冒烟记录另存 `pi_smoke_test.jsonl`

### pi harness Stage 2 (agentic) dev results
**Path**: `outputs/predictions/pi_agentic_qwen3-vl-plus_dev_20260806.jsonl`
**Produced by**: `agent/eval_pi_agentic.py`
**Format**: 同 Stage 1（raw_answer 为轨迹末尾 800 字符）
**Notes**: pi 原生工具（bash/read）自主分析, 403 samples, **53.8%**; 与 S1 union oracle 71.7%; run log `runs/2026-08-06_pi_stage2_agentic_dev.md`; 完整轨迹在 `~/.pi/agent/sessions/--tmp-pi_ws_*`（1.9GB,含 agent 看过的帧）

### pi Case Viewer 数据包
**Path**: `web/case_viewer/data/`（gitignored,~80MB）
**Produced by**: `scripts/build_case_viewer.py`
**Format**: `cases.json`（S1/S2 join + 轨迹事件）+ `images/<id>/*.jpg`（agent 看过的帧,640px）
**Notes**: 前端 `scripts/pi_case_viewer.py`（Flask :7875）读取;重跑评测后重新构建

### pi 观察原语系列 (S2.1~S2.4b, 90 题均匀子集)
**Path**: `outputs/predictions/pi_agentic_ext{,2,3,4b}_qwen_pt6_20260807.jsonl` + `pi_agentic_ext4_...`（无效实验,保留供审计）
**Produced by**: `agent/eval_pi_agentic.py --per-task 6` + `VISTR_PI_EXTENSION`
**Format**: 同 Stage 2
**Notes**: S2.1 多图 51.1% / S2.2 index 51.1% / S2.3 read_crop 48.9% / **S2.4b semantic_crop 56.7%**; run log `runs/2026-08-07_pi_observation_primitives.md`; grounding 探针 `outputs/grounding_probe/`

### claude-opus-4-6 via pi 结果
**Path**: `outputs/predictions/pi_claude-opus-4-6_dev_20260807.jsonl`（S1 全量 403, **57.1%**）+ `pi_agentic_claude-opus-4-6_dev_20260807.jsonl`（S2 部分 48/403,用户叫停）
**Produced by**: `agent/eval_pi.py` / `eval_pi_agentic.py`（VISTR_PI_PROVIDER=idealab-anthropic）
**Notes**: idealab 网关偶发 "use case" 错误→脚本已带重试;S2 需 --timeout 1200

### pi S2.5 evidence board 结果
**Path**: `outputs/predictions/pi_agentic_ext5_qwen_pt6_20260808.jsonl`（tail 模式）+ `pi_agentic_ext5b_qwen_pt6_20260808.jsonl`（anchor 模式）
**Produced by**: `agent/eval_pi_agentic.py` + `evidence_ledger.ts`
**Format**: 同 Stage 2
**Notes**: S2.5a tail 56.7% / S2.5b anchor 54.4%（90 题均匀子集）;结论:注入 evidence board 改变推理心态但不提升总分

### pi S2.6 evidence closure 结果
**Path**: `outputs/predictions/pi_s26_pt6_20260808.jsonl`（per-task 6, **62.2%**）+ `pi_s26_pt1_20260808.jsonl`（per-task 1, 53.3%）
**Produced by**: `agent/eval_pi_agentic.py` + `vistr_video_tools.ts` + `evidence_closure.ts`
**Format**: 同 Stage 2,额外含 `closure` 字段（submit_calls, checker_reply）
**Notes**: silent ledger + submit_answer + VLM closure checker; 相比 S2.4b +5.5pp; Interaction/Mikado/Passage/Jenga/Swimming/Soccer 提升最大(+16~17pp each)
