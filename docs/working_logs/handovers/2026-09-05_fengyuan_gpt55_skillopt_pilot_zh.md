---
status: ready-for-recipient
date: 2026-09-05
recipient: fengyuan
scope: skill-optimization
language: zh-CN
---

# Fengyuan 师兄交接：GPT-5.5 ViSTR 与 DocVQA SkillOpt 对比实验

英文版：
[`2026-09-05_fengyuan_gpt55_skillopt_pilot.md`](2026-09-05_fengyuan_gpt55_skillopt_pilot.md)

## 1. 实验目标与结论边界

请完成一个固定的、单随机种子的 100+100 pilot，对比 SkillOpt 分别作用于：

1. ViSTR-Bench Public 上的 4D-Agent S2.8 视频工具 Agent；
2. DocVQA 上 SkillOpt 原生的单轮 Agent。

每个 benchmark 的主结果定义为：

```text
有效更新率（Effective Update Rate）
= Fast step 中 action 为 accept 或 accept_new_best 的数量
  / history.json 中全部 Fast step 的数量
```

一次完整正式运行必须包含 16 个 Fast Update Steps。`reject` 与 `skip_*` 都计入
分母。每个 epoch 边界的 slow update 及其 `force_accept` 不计入分子或分母。

本实验检验的假设是：ViSTR 中“答案正确但过程无效”的轨迹可能给 SkillOpt 提供
误导性的正样本反思信号，从而降低 Candidate Skill 通过 validation gate 的速度。
这个 pilot 可以报告两个系统更新率是否存在相关差异，但不能单独证明差异由 Outcome
False Positive 导致，因为两个系统的 Agent 形态、模态、工具、初始 Skill 和答案空间
也不相同。

## 2. 固定实验协议

| 设置 | ViSTR | DocVQA |
|---|---|---|
| 总数据量 | 100 | 100 |
| Train / validation / test | 20 / 10 / 70 | 20 / 10 / 70 |
| 抽样与划分 seed | 43 | 43 |
| Fast batch size | 5 | 5 |
| Epoch / Fast step | 4 / 16 | 4 / 16 |
| Target 与 optimizer | GPT-5.5 | GPT-5.5 |
| Reasoning effort | medium | medium |
| SkillOpt 输出上限 | 16,384 | 16,384 |
| 初始 Skill | S2.8 Skill | 原生 DocVQA Skill |
| Agent | Pi 多轮工具 Agent | 原生单轮 DocVQA Agent |

余弦 edit budget 固定为：

```text
4, 4, 4, 4, 4, 3, 3, 3, 3, 3, 2, 2, 2, 2, 2, 2
```

正式运行开始后，不要修改抽样、split membership、prompt、工具、gate、slow/meta
设置、重试策略，或者只修改一侧的 API 行为。如果 GPT 兼容性要求修改公共适配层，
必须让同一修改同时作用于两个条件，重新通过 paired smoke，并在新的空 output root
中重新启动两边正式实验。

## 3. 仓库布局

两个仓库必须互为 sibling。配置使用相对路径，启动时还会验证 SkillOpt 的确切 commit
和干净工作树：

```text
<parent>/
├── 4D-Agent/
└── SkillOpt/
```

安装命令：

```bash
mkdir -p Spatial-Agent
cd Spatial-Agent
git clone --branch dev https://github.com/tangqh03/4D-Agent.git
git clone https://github.com/microsoft/SkillOpt.git
git -C SkillOpt checkout db46cd9ae7ce12f1dbd73c945185816aa738751d
git -C SkillOpt status --short
```

最后一条命令必须没有输出。如果 SkillOpt commit 不一致或存在 tracked 修改，4D-Agent
会拒绝启动，从而保证实验使用参考实现。

每次付费运行前记录：

```bash
git -C 4D-Agent rev-parse HEAD
git -C 4D-Agent status --short
git -C SkillOpt rev-parse HEAD
nvidia-smi
```

## 4. 新机器要求

当前交接支持的主路径为：

- NVIDIA GPU 的 Linux 机器；
- Python 3.11，并安装 `venv`；
- NVIDIA driver 能支持 PyTorch CUDA 12.8 wheel；
- Node.js 不低于 22.19，并安装 npm；
- Git、curl、ffmpeg 和 ffprobe；
- ffmpeg 包含 `libx264` encoder；
- GroundingDINO 至少约 8GB GPU 显存余量；
- 至少 100GB 空闲磁盘，用于环境、模型、数据和较大的 Pi 轨迹。

Ubuntu 系统准备示例：

```bash
sudo apt-get update
sudo apt-get install -y git curl ffmpeg
node --version
npm --version
nvidia-smi
ffmpeg -hide_banner -encoders 2>/dev/null | grep libx264
```

如果系统没有 Python 3.11，或 Node 低于 22.19，请使用所在机器/集群的标准包管理方式
安装，例如创建一个只用于 bootstrap 的 Python 3.11 conda 环境。不同 Ubuntu 版本的
默认 APT 源提供的 Python minor 不同，因此不要假设 `apt install python3.11` 在所有
机器上都可用。不要复用旧服务器的绝对 Python 路径；GPT profile 使用仓库内的
`.venv`。

## 5. 安装 Python 与 Pi

进入 `4D-Agent/` 后执行：

```bash
HANDOVER_PYTHON="$(command -v python)" bash scripts/setup_handover_env.sh
```

该脚本会：

- 创建 `.venv`；
- 安装 PyTorch 2.10.0、torchvision 0.25.0 与 CUDA 12.8 wheel；
- 安装 `requirements.handover.txt`；
- 以 editable 模式安装 sibling SkillOpt；
- 根据 Git 中的 npm lock 安装 Pi 0.84.0；
- 重新应用已有的 cumulative tool-argument stream 兼容补丁。

若目标机必须使用另一个官方 PyTorch wheel index，请显式指定并写入 run log：

```bash
HANDOVER_TORCH_INDEX_URL=<official-pytorch-index> \
HANDOVER_PYTHON=python3.11 \
bash scripts/setup_handover_env.sh
```

本 pilot 中不要替换 Pi 或 SkillOpt 版本。

## 6. 下载数据集与 GroundingDINO

环境中已经包含 `hf` CLI 和 Xet 支持。如果公开下载要求登录，再执行 Hugging Face
登录。

### 6.1 ViSTR-Bench Public

公开数据集地址为
[`homothetic/ViSTR-Bench-Public`](https://huggingface.co/datasets/homothetic/ViSTR-Bench-Public)，
固定 revision `d87a003751e618304ab03743658e8e2f96bb0ae5`：

```bash
.venv/bin/hf download homothetic/ViSTR-Bench-Public \
  --repo-type dataset \
  --revision d87a003751e618304ab03743658e8e2f96bb0ae5 \
  --local-dir data/benchmarks/ViSTR-Bench-Public
```

预期得到 `data.json`、652 个 MP4 和 670 条 QA。安装阶段不要复制或生成
`.frame_cache`；它只是可以重建的缓存。

### 6.2 DocVQA

当前实验只使用 6 个 validation parquet shards。根据 SkillOpt 发布的 534-ID pool，
固定源数据 revision：

```bash
.venv/bin/hf download lmms-lab/DocVQA \
  --repo-type dataset \
  --revision 539088ef8a8ada01ac8e2e6d4e372586748a265e \
  --include 'DocVQA/validation-*.parquet' README.md \
  --local-dir data/benchmarks/DocVQA
```

预期为 6 个 shards、5,349 条带 gold answer 的 validation records。官方无答案
test split 不参与本实验。

### 6.3 GroundingDINO

```bash
.venv/bin/hf download IDEA-Research/grounding-dino-base \
  --revision 12bdfa3120f3e7ec7b434d90674b3396eccf88eb \
  --local-dir models/grounding-dino-base
```

Runner 会在 GPU 0 上管理 `127.0.0.1:7876` 的服务：已有健康服务时复用，否则启动
自己的服务，并且退出时只停止自己启动的进程。GroundingDINO 只在本地接收抽取帧；
Policy 和 Observer 的图像输入继续按照 Pi 的正常 OpenAI API 路径发送。

## 7. 配置 GPT-5.5 medium

创建不入 Git 的凭证文件：

```bash
cp .env.gpt55.example .env.gpt55
chmod 600 .env.gpt55
```

只需要填入 API key：

```dotenv
POLICY_API_BASE_URL=https://api.openai.com/v1
POLICY_API_KEY=<fengyuan-openai-api-key>
PERCEPTION_URL=http://127.0.0.1:7876
```

不要提交、发送或把 `.env.gpt55` 粘贴进日志。YAML source of truth 是
`configs/agent/s2_8_gpt55.yaml`：

```text
模型：gpt-5.5
Pi reasoning level：medium
Pi Policy 单次输出上限：65,536
SkillOpt target/optimizer 单次输出上限：16,384
Skill full rewrite 输出上限：64,000
```

集成层会把官方 OpenAI 调用路由到 SkillOpt 原生 `openai_chat` backend，发送
`max_completion_tokens` 和 medium reasoning。Observer 子调用也使用
`max_completion_tokens`、medium reasoning，并且不发送不受支持的 `temperature`。
DeepSeek/OpenRouter 兼容行为保持不变。

OpenAI 官方模型页确认 GPT-5.5 支持图像输入、Chat Completions、function calling、
medium reasoning 及相应模型上限：
<https://developers.openai.com/api/docs/models/gpt-5.5>。

尽管 OpenAI 对新建的长程工具系统一般建议使用 Responses API，本实验为了保持固定
Pi/SkillOpt 实现而继续使用 Chat Completions。不要只迁移一侧。

## 8. 四阶段执行门禁

### Gate A：离线安装与数据预检

```bash
.venv/bin/python scripts/handover_preflight.py
```

该命令检查 Python packages、NVIDIA CUDA、Pi 0.84.0、ffmpeg/libx264、确切且干净
的 SkillOpt、全部 ViSTR 视频、DocVQA shard 数量以及 GroundingDINO 文件。继续前
必须修复所有 `FAIL`。

然后运行离线回归：

```bash
.venv/bin/python agent/tests/test_handover.py
.venv/bin/python agent/tests/test_skillopt_comparison.py
.venv/bin/python agent/tests/test_skillopt_bridge.py
.venv/bin/python agent/tests/test_runtime.py
.venv/bin/python agent/tests/test_eval_pi_parse.py
node agent/pi_ext/tests/run.mjs
```

这些测试不会调用 GPT，也不会启动 GroundingDINO。

### Gate B：一次付费 OpenAI 请求形状探针

```bash
.venv/bin/python scripts/handover_preflight.py --api
```

该命令执行一次含图片和 required function call 的 GPT-5.5 请求，用来确认账户、
模型权限和 Chat Completions 请求字段；它不会打印 API key。

### Gate C：物化固定样本

```bash
.venv/bin/python -u -m agent.skillopt.prepare_comparison \
  --config configs/skillopt/comparison_100.yaml
```

预期输出：

```text
ViSTR: 100 items, 15 tasks
DocVQA: 100 items, 100 unique images
Splits: train=20 val=10 test=70
```

生成的 DocVQA CSV 包含当前机器的图片绝对路径，因此不要复制另一台机器的
`data/skillopt_comparison/seed43/`；必须在最终运行机器上重新物化。

### Gate D：两边真实 smoke

先运行 DocVQA，以较低成本验证 target/optimizer；再运行 ViSTR，验证 Pi、Observer、
工具、GroundingDINO、HTML export 与 retry：

```bash
.venv/bin/python -u -m agent.skillopt \
  --config configs/skillopt/docvqa_comparison_100_gpt55.yaml \
  --smoke

.venv/bin/python -u -m agent.skillopt \
  --config configs/skillopt/vistr_comparison_100_gpt55.yaml \
  --smoke
```

生成仅用于 smoke 的报告：

```bash
.venv/bin/python -u -m agent.skillopt.compare_runs \
  --vistr outputs/skillopt/comparison_seed43_gpt55/vistr_smoke \
  --docvqa outputs/skillopt/comparison_seed43_gpt55/docvqa_smoke \
  --out outputs/skillopt/comparison_seed43_gpt55/smoke_report \
  --expected-steps 1
```

正式运行前，检查两边 `history.json`、至少一条 ViSTR 原生 HTML 轨迹，并确认没有把
provider 或配置失败错误地评分为 agent result。

## 9. 正式运行与 resume

请使用持久终端会话。两个条件可以独立运行，但不要让多个进程指向同一个 output
root。

DocVQA：

```bash
.venv/bin/python -u -m agent.skillopt \
  --config configs/skillopt/docvqa_comparison_100_gpt55.yaml
```

ViSTR：

```bash
.venv/bin/python -u -m agent.skillopt \
  --config configs/skillopt/vistr_comparison_100_gpt55.yaml
```

重复完全相同的命令会从 `runtime_state.json` resume。不要删除 partial state。无新
step 的 no-op resume 会保留原始 summary。如果因兼容性修改而必须重跑，请选择新
的 `env.out_root`，不要复用由不同请求行为产生的 history。

每个 benchmark 最坏约有 590 次 target Rollouts。每个 ViSTR Rollout 又可能包含
最多 3 次、每次 600 秒的 Pi Attempt。带大量图片的 JSONL/HTML 轨迹可能占用数十
GB，因此正式运行期间需要持续监控磁盘。

## 10. 失败分类

### 保留为实验结果

- 最终答案错误；
- 按配置执行 `600s × 3` 后仍没有答案；
- 合法反思没有产生 patch；
- Candidate Skill 被 validation gate reject 或 skip。

这些现象属于 agent/optimizer 行为，必须保留在当前实验中。

### 中止、修复，并在新 root 中重新运行两边

- 请求字段或模型行为不兼容导致 OpenAI 400；
- OpenAI 401/403 或 model-not-found；
- 429/5xx 持续到耗尽内部重试；
- 数据或模型文件缺失/损坏；
- Pi executable 或版本不一致；
- GroundingDINO、CUDA 或服务失败；
- SkillOpt checkout commit 变化或工作树变脏。

必须记录失败、代码修改、新的 4D-Agent commit、paired smoke 结果和新 output roots。
同一兼容性修改必须作用于两个系统。

## 11. 生成正式对比报告

只有两边 history 都恰好包含 16 个 Fast steps 时才能执行：

```bash
.venv/bin/python -u -m agent.skillopt.compare_runs \
  --vistr outputs/skillopt/comparison_seed43_gpt55/vistr \
  --docvqa outputs/skillopt/comparison_seed43_gpt55/docvqa \
  --out outputs/skillopt/comparison_seed43_gpt55/report \
  --expected-steps 16
```

生成的 JSON/Markdown 报告包括：

- Effective Updates 与 Effective Update Rate；
- patch、candidate、reject 和 skip steps；
- benchmark 内部 validation/test 的变化；
- 单独报告的 slow update actions；
- target Rollouts、failures、Attempts 与 timeout Attempts；
- SkillOpt token usage。

不要横向比较 ViSTR 和 DocVQA 的绝对准确率；应比较各系统自己的更新率和辅助诊断。

## 12. 需要交回的实验材料

请交回：

1. `outputs/skillopt/comparison_seed43_gpt55/vistr/{summary.json,history.json,best_skill.md}`；
2. `outputs/skillopt/comparison_seed43_gpt55/docvqa/{summary.json,history.json,best_skill.md}`；
3. 完整的 `outputs/skillopt/comparison_seed43_gpt55/report/`；
4. 一份 run log，记录 4D-Agent/SkillOpt commits、GPT model ID、reasoning level、
   GPU/CUDA、起止时间、兼容性修改和失败；
5. 足够审计 accepted/rejected steps 的 ViSTR 原生 JSONL/HTML 轨迹；
6. 一段只陈述相关性、不声称因果证明的简短结论。

完成检查表：

```text
[ ] 离线 preflight 通过
[ ] 付费多模态 function-call probe 通过
[ ] 在目标机重建 seed-43 数据并检查 manifest
[ ] DocVQA GPT smoke 通过
[ ] ViSTR GPT smoke 通过，且原生 HTML 可打开
[ ] DocVQA 正式 history 有16个 Fast steps
[ ] ViSTR 正式 history 有16个 Fast steps
[ ] compare_runs --expected-steps 16 通过
[ ] 报告两个 Effective Update Rates
[ ] 完整实验中不包含基础设施失败
[ ] 记录 provenance，并且结论只表述相关性
```

## 13. 关键实现位置

- GPT runtime 配置：`configs/agent/s2_8_gpt55.yaml`
- 正式实验配置：`configs/skillopt/*_comparison_100_gpt55.yaml`
- 环境安装：`scripts/setup_handover_env.sh`
- Preflight：`scripts/handover_preflight.py`
- 固定抽样：`agent/skillopt/prepare_comparison.py`
- Provider 路由：`agent/skillopt/integration.py::_configure_skillopt_models`
- 训练入口：`agent/skillopt/integration.py::run_training`
- 指标与报告：`agent/skillopt/compare_runs.py`
- 架构图：`docs/code_maps/systems/skillopt_vistr_training.md`
- 先前 DeepSeek smoke（只作为管线证据）：
  `docs/working_logs/runs/2026-09-05_skillopt_cross_benchmark_smokes.md`
