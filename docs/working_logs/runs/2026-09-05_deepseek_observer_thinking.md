---
status: completed
date: 2026-09-05
scope: s2.8-observer
---

# DeepSeek Observer thinking compatibility

## Goal

Keep the Policy reasoning behavior owned by Pi while preventing short Observer
caption and candidate-selection subcalls from spending their output budget on
DeepSeek's default-on thinking mode.

## Change

- Detect DeepSeek by the parsed Observer Base URL hostname (`deepseek.com` or a
  subdomain).
- Add `thinking: {type: "disabled"}` to both `index_video` caption requests and
  `semantic_crop` candidate-selection requests for DeepSeek only.
- Leave request bodies for every other OpenAI-compatible provider unchanged.

## Verification

```text
node agent/pi_ext/tests/run.mjs
33/33 passed, including explicit DeepSeek and OpenRouter request-shape coverage

/opt/conda/bin/python agent/tests/test_runtime.py
13 tests passed

/opt/conda/bin/python agent/tests/test_eval_pi_parse.py
21 checks passed

/opt/conda/bin/python -m compileall -q agent/runtime agent/datasets agent/tests/test_runtime.py
passed

git diff --check
passed
```

No provider request, GPU inference, or benchmark evaluation was run.
