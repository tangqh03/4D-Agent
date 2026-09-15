---
status: completed
date: 2026-09-15
scope: skill-optimization-artifacts
---

# Experiment-local ViSTR SkillOpt trajectories on dev

## Implementation

- New ViSTR SkillOpt runs override only the runner artifact root to
  `<out_root>/trajectories/`.
- Rollout paths become descriptive group names containing split and available
  epoch, step, batch, stage, and Skill origin.
- `trajectory_index.json`, per-item `source_trajectory.json`, and rollout
  `results.jsonl` expose complete paths and structured context.
- Existing runs preserve their legacy native root and receive relative symbolic
  links, so resume caches and large artifacts are not copied or moved.

## Verification

```text
python -m py_compile agent/skillopt/integration.py agent/tests/test_skillopt_bridge.py
python -m unittest agent.tests.test_skillopt_bridge
git diff --check
```

Observed: all 11 focused bridge tests passed, including descriptive
split/epoch/step naming, experiment-local linking/indexing, and legacy native
run-ID reuse. The requested legacy-run backfill is recorded separately after
the code commit.
