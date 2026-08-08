---
status: active
scope: general
last_verified: 2026-08-01
owner: gaozhe
---

# Script Registry

Index of all scripts in this project. Each entry documents purpose, usage, inputs, and outputs.

## Format

```markdown
### path/to/script.sh
**Purpose**: One-line description.
**Usage**: `command to run`
**Inputs**: What it reads
**Outputs**: What it produces
**Notes**: Any caveats
```

---

## Agent 包（`agent/`）

### agent/coding_agent/eval_coding_agent.py
**Purpose**: V4 action plan pipeline 批量评测（checkpoint/resume）
**Usage**: `/opt/conda/bin/python agent/coding_agent/eval_coding_agent.py [--split dev] [--tasks T1,T2] [--limit N] [--resume] [--workers 1]`
**Inputs**: benchmark `data.json` + 视频 + `agent/llm_keys.local.json`
**Outputs**: `outputs/predictions/coding_agent_<timestamp>.jsonl`
**Notes**: 支持 `VISTR_LLM_MODEL` 环境变量切换模型

### agent/eval_baseline.py
**Purpose**: baseline 直接推理评测（frames + question → answer，无工具）
**Usage**: `[VISTR_LLM_MODEL=xxx] /opt/conda/bin/python agent/eval_baseline.py [--split dev] [--limit N] [--resume] [--max-tokens 500]`
**Inputs**: benchmark `data.json` + 视频 + `agent/llm_keys.local.json`
**Outputs**: `outputs/predictions/baseline_<model>_<timestamp>.jsonl`
**Notes**: 支持 `VISTR_LLM_MODEL` 环境变量切换模型

### agent/eval_pi.py
**Purpose**: pi harness 评测（Stage 1: 抽帧 + `pi -p` 带图问答,无工具）
**Usage**: `/opt/conda/bin/python -u agent/eval_pi.py [--split dev] [--limit N] [--resume] [--workers 4]`
**Inputs**: benchmark `data.json` + 视频; pi 安装于 `third_party/pi-runtime/`; provider 配置 `~/.pi/agent/models.json`（含 key,chmod 600,repo 外）
**Outputs**: `outputs/predictions/pi_<model>_<timestamp>.jsonl`
**Notes**: 环境变量 `VISTR_PI_PROVIDER` / `VISTR_PI_MODEL` 切换; pi session 会积累在 `~/.pi/agent/sessions/`,量大需清理

### agent/pi_ext/vistr_video_tools.ts
**Purpose**: pi extension — 观察原语五件套(index_video / read_video_sequence / read_multiframe / read_crop / semantic_crop)
**Usage**: `pi -p -e agent/pi_ext/vistr_video_tools.ts ...` 或评测脚本 `VISTR_PI_EXTENSION` 环境变量
**Inputs**: workspace 内视频/图片;semantic_crop 依赖 perception 服务(:7876);caption/selection subcall 走 `~/.pi/agent/models.json` 网关
**Notes**: 全部 task-agnostic;code map `docs/code_maps/systems/pi_observation_stack.md`

### agent/run_plan_verify.py
**Purpose**: 二阶段探究 runner——qwen3-vl-plus 对每题做 plan + verify 双隔离调用
**Usage**: `/opt/conda/bin/python -u agent/run_plan_verify.py [--limit N] [--workers 8] [--task Basketball_Shot]`
**Inputs**: benchmark `data.json` + 视频（16 帧均匀抽样 base64）；`agent/llm_keys.local.json`（chmod 600，双 key）
**Outputs**: `outputs/plan_verify/qwen3-vl-plus_plan_verify.jsonl`（断点续跑，按 id 跳过）
**Notes**: PLAN/VERIFY 为独立会话（无共享历史）；各产出 plan文本/checklist/answer/confidence

### agent/llm.py
**Purpose**: AMAP 网关 OpenAI 兼容客户端（urllib 零依赖；key 轮换；429/5xx 指数退避）
**Notes**: keys 只存 `agent/llm_keys.local.json`，勿写入任何文档

### agent/prompts.py
**Purpose**: PLAN/VERIFY prompt 模板 + 消息组装（文本+16 帧图像）

## Root-level Python

### scripts/build_case_viewer.py
**Purpose**: 生成 pi case viewer 数据包(S1/S2 预测 join + pi session 轨迹/看过的帧提取)
**Usage**: `/opt/conda/bin/python scripts/build_case_viewer.py`
**Inputs**: `outputs/predictions/pi_*_dev_20260806.jsonl` ×2 + `~/.pi/agent/sessions/--tmp-pi_ws_*`
**Outputs**: `web/case_viewer/data/`(cases.json + 缩略帧,~80MB,gitignored)
**Notes**: 轨迹按题目文本+答案指纹匹配 session;重跑评测后需重新构建

### scripts/pi_case_viewer.py
**Purpose**: pi case 浏览前端(S1/S2 对比、视频回放、Stage2 工具轨迹+看过的帧);Flask 单页 + 相对路径 API,代理友好(参考 7874 的 v3_case_viewer 模式)
**Usage**: `/home/admin/.conda/envs/star/bin/python -u scripts/pi_case_viewer.py --port 7875`;notebook 代理访问 `/proxy/7875/`
**Inputs**: `web/case_viewer/data/`(先跑 build_case_viewer.py)+ benchmark 视频
**Notes**: 无 websocket 依赖;`web/case_viewer/index.html` 为静态版备用

### scripts/upload_hf_pi_trajs.py
**Purpose**: 打包 S1/S2 pi 轨迹(session JSONL + manifest)并上传 HF dataset(`MihailSlutsky/vistr-pi-trajectories`)
**Usage**: `HF_ENDPOINT=https://hf-mirror.com /home/admin/.conda/envs/star/bin/python -u scripts/upload_hf_pi_trajs.py [--skip-upload]`
**Inputs**: `~/.pi/agent/sessions/` + `outputs/predictions/pi_*_dev_20260806.jsonl`;token `/mnt/xlab-nas-wm/gaozhe.gz/hf_datasets/hf_tokens.txt`
**Outputs**: `outputs/hf_export/stage{1,2}_trajectories.tar.gz`
**Notes**: S1 按首帧 md5 匹配(题目文本同任务内重复);S2 按题目+答案指纹;参考 GenDoP upload 模式

### scripts/perception_service.py
**Purpose**: 常驻 perception model-pool 服务(GroundingDINO GPU 常驻;可扩 SAM2/DA3/VGGT)
**Usage**: `nohup /home/admin/.conda/envs/star/bin/python -u scripts/perception_service.py --port 7876 --eager > /tmp/perception_service.log 2>&1 &`
**Inputs**: 权重 `/mnt/xlab-nas-wm/gaozhe.gz/hf_datasets/grounding-dino-base`
**Outputs**: HTTP `/health` `/ground` `/annotate`(供 semantic_crop extension 调用)
**Notes**: extension 禁止自行加载权重;文本 prompt 仅英文(BERT 词表)

### scripts/grounding_probe.py
**Purpose**: semantic_crop vs read_crop 小规模 grounding 对比(5 探针,首发命中率/调用次数)
**Usage**: `/opt/conda/bin/python scripts/grounding_probe.py --tool semantic_crop|read_crop`
**Outputs**: `outputs/grounding_probe/<tool>/`(crop 图)+ `<tool>_results.json`
**Notes**: 需 perception 服务(7876)在线;探针为 task-agnostic 目标描述

### visualize_results.py
**Purpose**: ViSTR-Bench 可视化前端 — leaderboard 总览 dashboard（PNG）+ 样本级回放视频（MP4）
**Usage**: `/opt/conda/bin/python visualize_results.py [--mode overview|samples] [--results outputs/predictions/xxx.jsonl]`
**Inputs**: `outputs/predictions/*.jsonl`（每行一个样本：id/task/question/options/gt/pred/reasoning/video 等）
**Outputs**: `data/visualizations/overview_dashboard.png`、`data/visualizations/samples/<id>_replay.mp4`
**Notes**: 内置 `--demo` 生成 mock 数据用于冒烟；详见 `docs/agent/skills/visualize_benchmark_results/SKILL.md`

### web_frontend.py（已废弃）
**Status**: DEPRECATED 2026-08-01 — stdlib 手写视频服务在浏览器下播放不稳，被 Streamlit 方案取代。文件保留仅作参考，勿再启动。
**替代**: `scripts/vistr_viewer.py`

### scripts/vistr_viewer.py
**Purpose**: Web 可视化前端（Streamlit）— Taxonomy / Leaderboard / Sample Browser 三页
**Usage**: `/opt/conda/envs/python3.10.13/bin/python -m streamlit run scripts/vistr_viewer.py --server.port 8731 --server.headless true`（或 `bash scripts/web_frontend.sh`）
**Inputs**: benchmark `data.json` + `outputs/predictions/*.jsonl` + `web/posters/`
**Outputs**: HTTP 服务于 8731
**Notes**: `st.video(本地路径)` 播视频（与 48901 同机制）；跳转用 on_click 回调改 session_state（widget 实例化后不可改）
**Code Map**: [`docs/code_maps/scripts/vistr_viewer.md`](../code_maps/scripts/vistr_viewer.md)

## Shell Scripts (`scripts/`)

### scripts/visualize.sh
**Purpose**: visualize_results.py 的封装（固定 python 路径与输出目录）
**Usage**: `bash scripts/visualize.sh [--samples <results.jsonl>] [--demo]`
**Inputs**: 同 visualize_results.py
**Outputs**: `data/visualizations/`
**Notes**: `set -e`；编码走 ffmpeg libx264（禁用 OpenCV mp4v）

### scripts/web_frontend.sh
**Purpose**: Streamlit 前端启动器（环境 `/opt/conda/envs/python3.10.13/bin/python`，与 48901 同款）
**Usage**: `bash scripts/web_frontend.sh [端口, 默认 8731]`；后台用 `nohup ... &`
**Outputs**: HTTP 服务（8731 端口）
**Notes**: 远端访问用 `ssh -L 8731:localhost:8731 <host>`

### scripts/extract_case_frames.py
**Purpose**: 逐 case 审查抽帧——每视频 4 帧拼 2×2 拼图（省 token），生成分层抽样 worklist
**Usage**: `/opt/conda/bin/python scripts/extract_case_frames.py [--n_per_task 5] [--seed 7]`
**Inputs**: benchmark `data.json` + 视频
**Outputs**: `docs/notes/analyses/2026-08-01_case_review/{worklist.json, frames/*.jpg}`
**Notes**: 抽样按答案类别分层+来源多样优先

### scripts/case_log_append.py
**Purpose**: 向 case_log.jsonl 追加结构化观察记录（stdin 收 JSON 数组）
**Usage**: `cat <<'JSON' | /opt/conda/bin/python scripts/case_log_append.py ... JSON`
**Outputs**: `docs/notes/analyses/2026-08-01_case_review/case_log.jsonl`

### scripts/gen_task_posters.py
**Purpose**: 为 taxonomy 页生成每任务代表帧海报（15 张）
**Usage**: `/opt/conda/bin/python scripts/gen_task_posters.py`
**Inputs**: benchmark `data.json` + 每任务首个视频
**Outputs**: `web/posters/<Task_Name>.jpg`（480×270）
