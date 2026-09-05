---
status: completed
date: 2026-09-05
scope: agent-config
---

# S2.8 provider configuration reference

## Changes

- Made the checked-in S2.8 configuration explicitly DeepSeek-oriented by using
  the `deepseek` provider alias and the vision model's display name.
- Preserved the existing 1M context and 32K Policy output settings.
- Updated `.env.example` to use the official DeepSeek Base URL by default.
- Added `configs/agent/README.md` with every schema-v1 field, path/secret
  semantics, and copyable DeepSeek, OpenRouter, and separate Observer recipes.
- Registered and cross-linked the reference from the runtime documentation.

## Verification

```text
AgentConfig.from_yaml("configs/agent/s2_8.yaml")
passed with policy/observer provider=deepseek

/opt/conda/bin/python agent/tests/test_runtime.py
13 tests passed

node agent/pi_ext/tests/run.mjs
33/33 passed

git diff --check
passed
```

No provider request, GPU inference, or benchmark evaluation was run.
