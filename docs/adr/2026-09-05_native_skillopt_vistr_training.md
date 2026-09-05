---
status: accepted
date: 2026-09-05
scope: skill-optimization
---

# ADR: Native SkillOpt training around the S2.8 runtime

## Context

The configurable S2.8 runtime already exposes candidate Skill text and
reflection-ready trajectories, but it does not update Skills. Reimplementing
SkillOpt inside 4D-Agent would create a second training algorithm whose patch,
gate, slow-update, and meta-skill behavior could drift from the requested
reference implementation.

The upstream DocVQA profile has the desired optimization recipe. Its dataset is
pre-split, while this ViSTR experiment instead receives a user-selected Public
ID pool and requires deterministic ratio splitting.

## Experiment data

The default ID pool contains all 670 local ViSTR-Bench Public questions. The
requested SkillOpt ratio `2:1:7` with seed 42 produces 134 train, 67 validation,
and 469 test items using the upstream largest-remainder calculation.

## Decision

Use the external SkillOpt checkout at a pinned clean commit and call its native
`ReflACTTrainer` through a thin ViSTR `EnvAdapter`. Inherit the DocVQA training
configuration, but keep target execution in the existing S2.8 `AgentRunner`.
Use SkillOpt's generic ratio splitter after filtering ViSTR by a user-provided
ID file. Evolve only the injected Skill body.

The optimizer inherits the policy's configured OpenAI-compatible provider,
model ID, and dotenv credential. Native Pi trajectories remain under the agent
artifact root; the SkillOpt experiment stores small compatible projections and
source links.

## Rationale

This preserves the reference training method without vendoring it, keeps model
and credential configuration in the established YAML/dotenv boundary, and
prevents Skill optimization from changing the fixed tool/runtime comparison.
Pinning the commit and split inputs makes resume fail closed instead of mixing
results from different algorithms or datasets.

## Consequences

- Running Skill optimization requires the configured SkillOpt source checkout.
- A different upstream commit or dirty tracked files stop the run until the
  experiment config is deliberately updated.
- The `2:1:7` split leaves 20% for training and 70% for final testing.
- DocVQA's single-turn image runtime settings do not override Pi's multi-turn
  video-agent settings.
- The optimizer and policy may share a model identity, but calls and contexts
  remain independent.
