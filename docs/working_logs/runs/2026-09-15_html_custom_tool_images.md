---
status: completed
date: 2026-09-15
scope: agent-runtime-artifacts
---

# Render custom-tool images in exported trajectory HTML

## Cause

Pi 0.84.0's self-contained HTML contained the complete session payload but its
template called `renderResultImages()` only for the built-in `read` tool.
ViSTR tools such as `read_multiframe`, `read_video_sequence`, `read_crop`, and
`semantic_crop` followed the custom/default branch, which rendered text but not
their image blocks. A checked test trajectory contained 19 embedded image
blocks and 19 decoded images even though the custom-tool views were absent.

## Fix

`export_and_materialize` now applies a small, version-checked presentation patch
after successful Pi export. It invokes the exporter's existing
`renderResultImages()` for non-`read` tool results; image bytes remain embedded
in the original self-contained format. If a future Pi template no longer has
the recognized insertion point, the HTML remains available and the attempt
records an artifact error instead of silently claiming the patch succeeded.

Existing HTML was not overwritten. The 40 best-skill test trajectories in
`qwen35-gemini38-critic-random100-2026-09-14_191925` received adjacent
`*.with-images.html` views covering 643 custom-tool image blocks. Their
per-item `source_trajectory.json` and `results.jsonl` metadata expose the views
through `session_html_with_images`.

## Verification

```text
python -m py_compile agent/runtime/artifacts.py agent/tests/test_runtime.py
python -m unittest agent.tests.test_runtime agent.tests.test_skillopt_bridge agent.tests.test_trajectory_critic_integration
```

Observed: 40/40 tests passed. Static inspection of item 1069's enhanced HTML
confirmed one renderer patch marker and 19 intact embedded session image blocks.
All 40 compatibility views passed the marker check and occupy 45,172,508 bytes.
