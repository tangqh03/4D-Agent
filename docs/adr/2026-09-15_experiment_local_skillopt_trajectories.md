---
status: active
date: 2026-09-15
scope: skill-optimization
---

# ADR: Keep ViSTR SkillOpt trajectories discoverable inside each experiment

## Context

ViSTR SkillOpt projections contain compact `conversation.json` files while the
complete Pi JSONL, HTML, decoded images, and canonical conversation previously
lived in a shared agent-level `trajectories/skillopt-<hash>/` directory. The
per-item `source_trajectory.json` retained the absolute source paths, but the
opaque hash did not reveal the owning experiment, split, epoch, step, stage, or
Skill version.

## Decision

New ViSTR SkillOpt runs store native trajectories below their own
`<out_root>/trajectories/` directory. Each rollout group receives a descriptive
name containing the split and all available epoch, step, batch, stage, and Skill
origin fields. The experiment also writes `trajectory_index.json`; per-item
`source_trajectory.json` files and `results.jsonl` rows record both the complete
experiment-local path and structured `run_context`.

When an existing run resumes with trajectories at the legacy shared root, it
continues using that root for cache/resume compatibility and exposes relative
symbolic links below the experiment's `trajectories/` directory. No existing
artifact is moved, copied, or deleted.

## Consequences

- Ordinary non-SkillOpt `AgentRunner` calls still use the artifact root from the
  agent YAML.
- New ViSTR SkillOpt output directories are self-contained for trajectory data.
- Legacy experiment directories may contain symbolic links whose targets must
  be retained if the experiment is archived.
- Existing consumers of `trajectory_dir` remain compatible; new tooling should
  prefer `experiment_trajectory_dir` and `run_context`.
