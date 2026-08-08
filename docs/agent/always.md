---
status: active
scope: general
last_verified: 2026-07-31
owner: gaozhe
---

# Agent Core Rules — Always Loaded

These rules apply to every session, every task, every agent.

## Session start

- Read `docs/working_logs/active.md` before doing anything.
- Read `docs/knowledge/vistr_bench.md` before benchmark-related work.
- If a plan exists in `plans/active/`, resume from where it left off.

## Permissions & safety

- Never delete files without explicit user confirmation.
- Never run destructive git ops (force-push, reset --hard) without asking.
- Long-running or expensive operations (GPU inference, batch evals, model/data downloads): always confirm first.
- Evaluations default to per-task uniform sampling (`--per-task N`, e.g. N=6 → 90 samples); full-split runs ONLY when the user explicitly asks (user rule, 2026-08-07).
- Iterate and tune ONLY on the ViSTR-Bench public split (670 QA pairs). The private held-out set is off-limits for any tuning.

## Environment

- Tooling/visualization Python: `/opt/conda/bin/python` (3.10.13, has cv2/matplotlib/numpy<2).
- GPU: AMD ROCm class hardware on this cluster — CUDA-only tool models need ROCm porting notes in `docs/knowledge/`.
- NAS paths are shared; do not write outside the project root without confirmation.

## Work habits

- Before modifying a script: check if a rule exists in `docs/agent/rules/` for that domain.
- Always add `-u` flag when running Python scripts in background (`nohup python -u ...`).
- Print timestamps at key pipeline stages for profiling.
- Visualize intermediate outputs where possible (evidence maps, tracked targets, dashboards).
- Video encoding: ffmpeg libx264 only; never OpenCV `mp4v` (produces garbled video on this system).
- After finishing work: update `active.md` with new state.
- Every experiment produces a run log in `docs/working_logs/runs/`.
- Every code change includes a smoke test command and its observed result.

## Documentation maintenance

Agent is responsible for keeping docs current. Rules for when to update:

| Trigger | Action |
|---------|--------|
| Plan completed | Archive plan → `completed/`, update `active.md`, register new assets |
| New script/dataset/output created | Add to relevant `registry/*.md` |
| Discovered a recurring pattern or pitfall | Write a rule (`rules/`) or playbook (`playbooks/`) |
| User gives feedback on approach | Update `always.md` or relevant rule |
| Experiment finished | Write run log to `working_logs/runs/` |
| Benchmark knowledge updated (paper re-read, leaderboard change) | Update `knowledge/vistr_bench.md` |

Commit message format for doc updates: `docs: <what changed>`

## Personal notes

- `docs/notes/` contains tentative human observations, ideas, and unverified analyses.
- Do not load notes by default.
- Read a note only when explicitly referenced or when searching for prior ideas.
- Treat notes as hypotheses, not verified facts.
- Do not promote note content into knowledge, plans, or decisions without user approval.

## Reporting

- Daily reports use topic-based format (see `docs/working_logs/daily/_TEMPLATE.md`).
- Group by work topic, not by completion status. Write naturally with inline details.
- End each topic with a status tag. No rigid "Key conclusions / Risks / Tomorrow" sections.
- For the full report generation procedure, see `docs/agent/skills/report_generation/SKILL.md`.

## Architecture decisions

- When making a significant technical choice (tool selection, data format, algorithm, configuration), write an ADR in `docs/adr/`.
- Use the template at `docs/adr/_TEMPLATE.md`.
- ADRs should capture: Context, Experiment data (if any), Decision, Rationale, Consequences.
- ADRs are reference material — they are not loaded every session but should be findable via `docs/registry/agent_system.md`.

## Communication

- When something fails, fix it immediately — don't ask whether to fix it.
- Be terse. Don't summarize what you just did unless asked.
