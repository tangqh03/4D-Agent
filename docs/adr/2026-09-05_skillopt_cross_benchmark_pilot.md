---
status: accepted
date: 2026-09-05
scope: skill-optimization
---

# ADR: Compare native ViSTR and DocVQA systems under one SkillOpt budget

## Context

Binary-choice ViSTR Trajectories can receive a correct outcome despite invalid evidence, while open-answer DocVQA has less opportunity for an accidental exact match. A system-level pilot will test whether the two real agents exhibit different SkillOpt update acceptance rates before investing in process-validity annotation or controlled label noise.

## Decision

Use seed 43 to draw 100 items per benchmark and split each into 20 train, 10
validation, and 70 test. Seed 43 is the first seed at or above 42 whose uniform
ViSTR sample covers all 15 tasks; it was selected without inspecting model
outcomes or DocVQA composition. Use batch size 5, four epochs, GPT-5.5 with
medium reasoning as both target and optimizer, and the same cosine edit
schedule, producing 16 Fast Update Steps per run. Keep each system's native
seed Skill and agent runtime. The earlier DeepSeek paired smoke remains
pipeline evidence only; the handed formal experiment uses the dedicated
GPT-5.5 profiles.

Count only Fast Update Steps accepted through strict validation improvement as Effective Updates. Report slow/meta updates separately because the default slow update can be force-accepted. Treat this as a single-seed correlation pilot: a difference in Effective Updates does not establish Outcome False Positives as the cause.

## Consequences

- Native seed quality, modality, tools, and agent shape remain intentional system-level differences.
- Absolute benchmark scores are not compared; only within-benchmark improvement and update rates are reported.
- A causal claim requires a later audited or synthetic-noise experiment.
- A Complete Comparison Run requires both histories to contain all 16 Fast
  Update Steps; infrastructure failures require paired restart under new
  output roots.
- The formal handover intentionally uses the `gpt-5.5` alias rather than a
  dated snapshot to match SkillOpt's default. This improves recipe alignment
  but weakens exact model reproducibility, so both conditions must run in the
  same time window and record their start/end times.
