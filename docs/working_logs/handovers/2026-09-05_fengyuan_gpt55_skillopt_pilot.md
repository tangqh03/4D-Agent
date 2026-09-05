---
status: ready-for-recipient
date: 2026-09-05
recipient: fengyuan
scope: skill-optimization
---

# Fengyuan handover: GPT-5.5 ViSTR versus DocVQA SkillOpt pilot

中文版：
[`2026-09-05_fengyuan_gpt55_skillopt_pilot_zh.md`](2026-09-05_fengyuan_gpt55_skillopt_pilot_zh.md)

## 1. Objective and claim boundary

Please run the fixed, single-seed 100+100 pilot that compares SkillOpt around:

1. the 4D-Agent S2.8 video/tool agent on ViSTR-Bench Public; and
2. SkillOpt's native one-turn agent on DocVQA.

The primary result for each benchmark is:

```text
Effective Update Rate
= count(Fast step action is accept or accept_new_best)
  / count(all Fast step records in history.json)
```

Each complete formal run must contain 16 Fast Update Steps. `reject` and
`skip_*` remain in the denominator. Epoch-level slow `force_accept` actions
are outside both numerator and denominator.

The hypothesis is that outcome-correct but process-invalid ViSTR Trajectories
may provide misleading positive reflection signals and therefore reduce the
rate at which Candidate Skills pass validation. This pilot can show a
system-level correlation in update rate. It cannot, by itself, prove that
Outcome False Positives caused the difference: agent shape, modality, tools,
seed Skill, and answer space also differ between the systems.

## 2. Fixed experimental contract

| Setting | ViSTR | DocVQA |
|---|---|---|
| Total items | 100 | 100 |
| Train / validation / test | 20 / 10 / 70 | 20 / 10 / 70 |
| Sample and split seed | 43 | 43 |
| Fast batch size | 5 | 5 |
| Epochs / Fast steps | 4 / 16 | 4 / 16 |
| Target and optimizer | GPT-5.5 | GPT-5.5 |
| Reasoning effort | medium | medium |
| SkillOpt output cap | 16,384 | 16,384 |
| Initial Skill | S2.8 Skill | native DocVQA Skill |
| Agent | Pi multi-turn + tools | native one-turn DocVQA |

The cosine edit budgets are fixed to:

```text
4, 4, 4, 4, 4, 3, 3, 3, 3, 3, 2, 2, 2, 2, 2, 2
```

Do not change sampling, split membership, prompts, tools, gate, slow/meta
settings, retry policy, or only one side's API behavior after a formal run has
started. If a shared compatibility change is required, apply it to both
conditions, rerun both smokes, and restart formal runs in empty output roots.

## 3. Repository layout

The repositories must be siblings because checked-in configs use relative
paths and SkillOpt startup verifies an exact clean commit:

```text
<parent>/
├── 4D-Agent/
└── SkillOpt/
```

Clone them as follows:

```bash
mkdir -p Spatial-Agent
cd Spatial-Agent
git clone --branch dev https://github.com/tangqh03/4D-Agent.git
git clone https://github.com/microsoft/SkillOpt.git
git -C SkillOpt checkout db46cd9ae7ce12f1dbd73c945185816aa738751d
git -C SkillOpt status --short
```

The final command must print nothing. The integration refuses a different
SkillOpt commit or tracked changes, preserving the reference implementation.

Before every paid run, record:

```bash
git -C 4D-Agent rev-parse HEAD
git -C 4D-Agent status --short
git -C SkillOpt rev-parse HEAD
nvidia-smi
```

## 4. Machine requirements

Supported handover path:

- Linux on an NVIDIA machine;
- Python 3.11 with `venv` support;
- NVIDIA driver compatible with PyTorch CUDA 12.8 wheels;
- Node.js 22.19 or newer and npm;
- Git, curl, ffmpeg, and ffprobe;
- ffmpeg built with the `libx264` encoder;
- at least 8GB GPU memory for GroundingDINO; and
- at least 100GB free disk for environments, models, data, and large Pi
  Trajectories.

Example Ubuntu system preparation:

```bash
sudo apt-get update
sudo apt-get install -y git curl ffmpeg
node --version
npm --version
nvidia-smi
ffmpeg -hide_banner -encoders 2>/dev/null | grep libx264
```

Install Python 3.11 and Node 22 LTS through your normal system/cluster package
manager (for example, a dedicated conda bootstrap environment) when they are
not already available. Ubuntu releases differ in which Python minors their
default APT repositories carry, so do not assume `apt install python3.11` is
portable. Do not use the old server's absolute Python paths; the GPT profile
uses the repository-local `.venv`.

## 5. Python and Pi installation

From `4D-Agent/`:

```bash
HANDOVER_PYTHON="$(command -v python)" bash scripts/setup_handover_env.sh
```

The script performs these pinned operations:

- creates `.venv`;
- installs PyTorch 2.10.0 / torchvision 0.25.0 CUDA 12.8;
- installs `requirements.handover.txt`;
- installs the sibling SkillOpt checkout in editable mode;
- installs Pi 0.84.0 from the tracked npm lock; and
- reapplies the existing cumulative tool-argument stream compatibility patch.

If the machine requires a different official PyTorch wheel index, set it
explicitly and record the value in the run log:

```bash
HANDOVER_TORCH_INDEX_URL=<official-pytorch-index> \
HANDOVER_PYTHON=python3.11 \
bash scripts/setup_handover_env.sh
```

Do not substitute a different Pi or SkillOpt version during this pilot.

## 6. Download datasets and GroundingDINO

Install/login to the Hugging Face CLI only if the public downloads require it.
The setup environment already includes `hf` and Xet support.

### 6.1 ViSTR-Bench Public

The public dataset is
[`homothetic/ViSTR-Bench-Public`](https://huggingface.co/datasets/homothetic/ViSTR-Bench-Public).
Pin revision `d87a003751e618304ab03743658e8e2f96bb0ae5`:

```bash
.venv/bin/hf download homothetic/ViSTR-Bench-Public \
  --repo-type dataset \
  --revision d87a003751e618304ab03743658e8e2f96bb0ae5 \
  --local-dir data/benchmarks/ViSTR-Bench-Public
```

Expected payload: `data.json` plus 652 MP4 files and 670 QA rows. Do not copy
or generate `.frame_cache` as part of installation; it is a rebuildable cache.

### 6.2 DocVQA

Only the six validation parquet shards are used. Pin the source recorded by
SkillOpt's released 534-ID pool:

```bash
.venv/bin/hf download lmms-lab/DocVQA \
  --repo-type dataset \
  --revision 539088ef8a8ada01ac8e2e6d4e372586748a265e \
  --include 'DocVQA/validation-*.parquet' README.md \
  --local-dir data/benchmarks/DocVQA
```

Expected payload: six shards and 5,349 validation rows. The official answerless
test split is not used.

### 6.3 GroundingDINO

```bash
.venv/bin/hf download IDEA-Research/grounding-dino-base \
  --revision 12bdfa3120f3e7ec7b434d90674b3396eccf88eb \
  --local-dir models/grounding-dino-base
```

The runner manages this service on GPU 0 at `127.0.0.1:7876`: it reuses a
healthy service and stops only one it started. GroundingDINO receives extracted
frames locally; Policy and Observer image inputs follow Pi's normal OpenAI API
path.

## 7. Configure GPT-5.5 medium

Create the untracked credential file:

```bash
cp .env.gpt55.example .env.gpt55
chmod 600 .env.gpt55
```

Edit only the key:

```dotenv
POLICY_API_BASE_URL=https://api.openai.com/v1
POLICY_API_KEY=<fengyuan-openai-api-key>
PERCEPTION_URL=http://127.0.0.1:7876
```

Never commit, paste into logs, or send `.env.gpt55`. The YAML source of truth is
`configs/agent/s2_8_gpt55.yaml`:

```text
model: gpt-5.5
Pi reasoning level: medium
Pi Policy output ceiling: 65,536
SkillOpt target/optimizer ceiling: 16,384
Skill full-rewrite ceiling: 64,000
```

The integration routes official OpenAI calls to SkillOpt's native
`openai_chat` backend so it sends `max_completion_tokens` and medium reasoning.
Observer subcalls also use `max_completion_tokens`, medium reasoning, and omit
unsupported `temperature`. DeepSeek/OpenRouter compatibility remains intact.

OpenAI's model page confirms GPT-5.5 image input, Chat Completions, function
calling, medium reasoning, and its model limits:
<https://developers.openai.com/api/docs/models/gpt-5.5>.

Although current OpenAI guidance generally prefers Responses for new
tool-heavy systems, this experiment deliberately stays on Chat Completions to
match the fixed Pi/SkillOpt implementation. Do not migrate only one condition.

## 8. Four execution gates

### Gate A: offline installation and data preflight

```bash
.venv/bin/python scripts/handover_preflight.py
```

This checks Python packages, NVIDIA CUDA, Pi 0.84.0, ffmpeg/libx264, exact clean
SkillOpt, all ViSTR videos, DocVQA shard count, and GroundingDINO files. Fix all
`FAIL` lines before continuing.

Run the offline regression gate as well:

```bash
.venv/bin/python agent/tests/test_handover.py
.venv/bin/python agent/tests/test_skillopt_comparison.py
.venv/bin/python agent/tests/test_skillopt_bridge.py
.venv/bin/python agent/tests/test_runtime.py
.venv/bin/python agent/tests/test_eval_pi_parse.py
node agent/pi_ext/tests/run.mjs
```

None of these commands calls GPT or starts GroundingDINO.

### Gate B: one paid OpenAI shape probe

```bash
.venv/bin/python scripts/handover_preflight.py --api
```

This makes one GPT-5.5 request containing an image and a required function
call. It verifies account/model access and the Chat Completions request fields
without printing the API key.

### Gate C: materialize the fixed sample

```bash
.venv/bin/python -u -m agent.skillopt.prepare_comparison \
  --config configs/skillopt/comparison_100.yaml
```

Expected:

```text
ViSTR: 100 items, 15 tasks
DocVQA: 100 items, 100 unique images
Splits: train=20 val=10 test=70
```

The generated DocVQA CSV stores machine-local absolute image paths, so always
regenerate it on the final machine rather than copying another machine's
`data/skillopt_comparison/seed43/` directory.

### Gate D: paired real smoke

Run DocVQA first because it cheaply validates the target/optimizer path, then
ViSTR to validate Pi, Observer, tools, GroundingDINO, HTML export, and retry:

```bash
.venv/bin/python -u -m agent.skillopt \
  --config configs/skillopt/docvqa_comparison_100_gpt55.yaml \
  --smoke

.venv/bin/python -u -m agent.skillopt \
  --config configs/skillopt/vistr_comparison_100_gpt55.yaml \
  --smoke
```

Generate a smoke-only report:

```bash
.venv/bin/python -u -m agent.skillopt.compare_runs \
  --vistr outputs/skillopt/comparison_seed43_gpt55/vistr_smoke \
  --docvqa outputs/skillopt/comparison_seed43_gpt55/docvqa_smoke \
  --out outputs/skillopt/comparison_seed43_gpt55/smoke_report \
  --expected-steps 1
```

Before formal execution, inspect both `history.json` files, at least one ViSTR
native HTML Trajectory, and confirm no provider/configuration failure was scored
as an agent result.

## 9. Formal execution and resume

Use persistent terminal sessions. Run the two conditions independently; do not
point concurrent processes at the same output root.

DocVQA:

```bash
.venv/bin/python -u -m agent.skillopt \
  --config configs/skillopt/docvqa_comparison_100_gpt55.yaml
```

ViSTR:

```bash
.venv/bin/python -u -m agent.skillopt \
  --config configs/skillopt/vistr_comparison_100_gpt55.yaml
```

Repeating the exact same command resumes from `runtime_state.json`. Do not
delete partial state. A no-op resume preserves the original summary. To restart
after a compatibility change, select a new `env.out_root`; do not reuse a
history produced under different request behavior.

The worst-case upper bound is roughly 590 target Rollouts per benchmark.
ViSTR Rollouts may each contain up to three 600-second Pi Attempts. Large
image-bearing JSONL/HTML Trajectories can consume tens of gigabytes; monitor
disk space throughout the run.

## 10. Failure classification

### Preserve as experiment outcomes

- wrong final answer;
- no answer after the configured `600s × 3` Pi attempts;
- a valid reflection producing no patch;
- a Candidate Skill rejected or skipped by the validation gate.

These describe the agent/optimizer and must remain in the run.

### Stop; fix; restart both conditions in new roots

- OpenAI 400 caused by request fields or unsupported model behavior;
- OpenAI 401/403 or model-not-found;
- sustained 429/5xx responses that exhaust retries;
- missing/corrupt data or model files;
- Pi executable/version mismatch;
- GroundingDINO/CUDA/service failure; or
- a changed/dirty SkillOpt checkout.

Record the failure, code fix, new 4D-Agent commit, paired smoke results, and new
output roots. The same compatibility change must apply to both systems.

## 11. Generate the formal comparison

Only proceed when both histories contain exactly 16 entries:

```bash
.venv/bin/python -u -m agent.skillopt.compare_runs \
  --vistr outputs/skillopt/comparison_seed43_gpt55/vistr \
  --docvqa outputs/skillopt/comparison_seed43_gpt55/docvqa \
  --out outputs/skillopt/comparison_seed43_gpt55/report \
  --expected-steps 16
```

The JSON and Markdown report include:

- Effective Updates and Effective Update Rate;
- patch, candidate, reject, and skip steps;
- validation and test changes within each benchmark;
- slow update actions reported separately;
- target Rollouts, failures, Attempts, and timeout Attempts; and
- SkillOpt token usage.

Do not compare absolute ViSTR and DocVQA accuracy. Compare their within-system
update rates and supporting diagnostics.

## 12. Required return package

Please return:

1. `outputs/skillopt/comparison_seed43_gpt55/vistr/{summary.json,history.json,best_skill.md}`;
2. `outputs/skillopt/comparison_seed43_gpt55/docvqa/{summary.json,history.json,best_skill.md}`;
3. the full `outputs/skillopt/comparison_seed43_gpt55/report/` directory;
4. a run log containing the 4D-Agent and SkillOpt commits, GPT model ID,
   reasoning level, GPU/CUDA, time range, compatibility changes, and failures;
5. enough ViSTR native JSONL/HTML Trajectories to audit accepted/rejected steps;
   and
6. a short conclusion phrased as correlation, not causal proof.

Completion checklist:

```text
[ ] offline preflight passed
[ ] paid multimodal function-call probe passed
[ ] fixed seed-43 data regenerated and manifest inspected
[ ] DocVQA GPT smoke passed
[ ] ViSTR GPT smoke passed and native HTML opened
[ ] formal DocVQA history has 16 Fast steps
[ ] formal ViSTR history has 16 Fast steps
[ ] compare_runs --expected-steps 16 passed
[ ] both Effective Update Rates reported
[ ] infrastructure failures excluded from the completed experiment
[ ] provenance and correlation-only conclusion recorded
```

## 13. Key implementation pointers

- GPT runtime config: `configs/agent/s2_8_gpt55.yaml`
- Formal configs: `configs/skillopt/*_comparison_100_gpt55.yaml`
- Environment installer: `scripts/setup_handover_env.sh`
- Preflight: `scripts/handover_preflight.py`
- Fixed sampling: `agent/skillopt/prepare_comparison.py`
- Provider routing: `agent/skillopt/integration.py::_configure_skillopt_models`
- Training entry: `agent/skillopt/integration.py::run_training`
- Metric/report: `agent/skillopt/compare_runs.py`
- Architecture map: `docs/code_maps/systems/skillopt_vistr_training.md`
- Prior DeepSeek smoke (pipeline evidence only):
  `docs/working_logs/runs/2026-09-05_skillopt_cross_benchmark_smokes.md`
