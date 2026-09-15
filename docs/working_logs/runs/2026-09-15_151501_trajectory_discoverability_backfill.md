---
status: completed
date: 2026-09-15
scope: qwen35-gemini38-vistr-seed43-run-2026-09-14_151501
---

# Backfill discoverable trajectories and image-visible HTML for run 151501

## Target

`outputs/skillopt/false_positive_seed43/vistr/qwen35-gemini38-vistr-seed43-run-2026-09-14_151501/`

The completed run uses four epochs with one Fast step per epoch. Its
`runtime_state.json` identifies the best Skill origin as `step_0004` and the
final Skill origin as `slow_update_epoch_04`.

## Backfill

- Created `trajectory_index.json` with 19 rollout groups and 520 item-rollouts.
- Created 19 relative symbolic links below the experiment's `trajectories/`.
- Names distinguish train/val/test and include available epoch, step, stage,
  batch, and Skill-origin context.
- Added `experiment_trajectory_dir` and `run_context` to all 520 per-item
  `source_trajectory.json` files and all 520 rollout result rows.
- Native shared trajectory directories were not moved, copied, or deleted.

The principal test directories are:

```text
trajectories/test__baseline-test__origin-initial-skill/
trajectories/test__best-skill-test__origin-step-0004/
trajectories/test__final-skill-test__origin-slow-update-epoch-04/
```

## HTML re-export

The 520 item-rollouts contain 526 actual Pi sessions because six attempts were
retried. All 526 base HTML files were re-exported through Pi 0.84.0. The
custom-tool image renderer was enabled on 525 sessions containing 7,796 image
blocks; the remaining session contains no custom-tool image. No model request,
external API call, or GPU job was used.

## Verification

Full consistency checks passed:

```text
indexed groups:              19
relative valid links:        19
per-item sources:           520
annotated result rows:      520
Pi sessions/base HTML:  526/526
custom-image sessions:      525
patched HTML:               525
custom-tool image blocks: 7,796
missing/malformed/failures:   0
```

Every experiment-local item path resolves to its original native directory;
every HTML has an embedded `session-data` payload; every session with a
custom-tool image has the renderer marker.
