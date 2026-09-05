---
status: completed
date: 2026-09-05
scope: handover-readiness
---

# Fengyuan GPT-5.5 handover readiness

## Goal

Make the seed-43 ViSTR/DocVQA SkillOpt pilot installable and operable on a new
NVIDIA machine, using GPT-5.5 with medium reasoning and an explicit 16-step
completion gate.

## Changes

- Added a repository-local `.venv` installer, pinned Python requirements, and
  tracked Pi 0.84.0 npm manifests.
- Added `s2_8_gpt55.yaml`, paired GPT SkillOpt profiles, and a separate GPT
  output root.
- Added strict `thinking_level` configuration and passed `medium` to Pi.
- Routed official OpenAI SkillOpt calls through the upstream `openai_chat`
  backend. Observer requests use `max_completion_tokens`, medium reasoning,
  and no temperature; DeepSeek/OpenRouter shapes remain unchanged.
- Added clean-machine offline checks plus an optional paid GPT image/function
  probe. No actual GPT request was made in this preparation run.
- Added `--expected-steps` to the comparison reporter so the formal handover
  command rejects histories that are not 16/16.
- Removed active Node-test dependence on the old repository and conda absolute
  paths.
- Documented fixed Hugging Face revisions, execution gates, failure
  classification, resume, disk risk, metric semantics, and return artifacts.

## Verification

```text
npm ci --dry-run --offline --ignore-scripts   passed
bash -n scripts/setup_handover_env.sh         passed
handover preflight --help / py_compile        passed
handover tests                                4/4 passed
comparison tests                              7/7 passed
SkillOpt bridge tests                         8/8 passed
runtime tests                                 15/15 passed
legacy parser tests                           21/21 passed
active S2.8 tool tests                        34/34 passed
```

The OpenAI test is a stubbed request-shape test. It verifies the selected
fields without network access or credentials. The full installer was not run
because it would create a second environment and redownload CUDA packages on
the source machine; the recipient's offline preflight is the clean-machine
acceptance test.

## Human review guide

```mermaid
flowchart LR
    Clone[Clone two pinned repos] --> Setup[setup_handover_env]
    Setup --> Data[HF pinned data and model]
    Data --> Offline[offline preflight]
    Offline --> Probe[paid GPT shape probe]
    Probe --> Smoke[paired smoke]
    Smoke --> Formal[paired 16-step runs]
    Formal --> Report[compare --expected-steps 16]
```

```text
load GPT YAML and untracked dotenv
pass medium reasoning to Pi and Observer
if host is api.openai.com:
    use GPT request fields and SkillOpt openai_chat
else:
    preserve generic DeepSeek/OpenRouter behavior
run both native systems under the same 16-step update budget
reject a final report unless both histories contain 16 steps
```

Key pointers:

- `scripts/setup_handover_env.sh`
- `scripts/handover_preflight.py`
- `agent.runtime.config.ModelConfig.thinking_level`
- `agent.runtime.runner.AgentRunner._pi_command`
- `agent.pi_ext.vistr_video_tools.observerCompletionOptions`
- `agent.skillopt.integration._configure_skillopt_models`
- `agent.skillopt.compare_runs.compare`
- `docs/working_logs/handovers/2026-09-05_fengyuan_gpt55_skillopt_pilot.md`
- `docs/working_logs/handovers/2026-09-05_fengyuan_gpt55_skillopt_pilot_zh.md`
