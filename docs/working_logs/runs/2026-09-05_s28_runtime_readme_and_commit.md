---
status: completed
date: 2026-09-05
scope: agent-runtime-documentation
---

# S2.8 runtime README and repository checkpoint

## Changes

- Replaced the root README's legacy V4 description with the supported
  configurable S2.8 architecture and data flow.
- Documented encapsulated internals, stable public APIs, the SkillOpt-facing
  `skill_content` seam, fixed Tool Bundle, required YAML/dotenv/path choices,
  single-item execution, resume semantics, and artifact layout.
- Linked the complete DeepSeek/OpenRouter field reference and current code maps.
- Added `models/` to `.gitignore` so local GroundingDINO weights cannot enter the
  repository checkpoint.

## Commit scope

The checkpoint includes the configurable runtime, ViSTR adapter, active S2.8
extension/tests, seed Skill, YAML/dotenv template, notebook smoke example, ADR,
code maps, registries, working logs, and user documentation. It excludes the
real dotenv, model weights, benchmark data, third-party packages, and generated
outputs.

## Verification

```text
/opt/conda/bin/python agent/tests/test_runtime.py
13 tests passed

/opt/conda/bin/python agent/tests/test_eval_pi_parse.py
21 checks passed

node agent/pi_ext/tests/run.mjs
33/33 passed

/opt/conda/bin/python -m compileall -q agent/runtime agent/datasets agent/tests/test_runtime.py
passed

README local-link check
10/10 targets passed

candidate-file secret scan
no suspicious literals found

git diff --check
passed
```

No provider call, model download, GPU inference, or benchmark evaluation was
run.
