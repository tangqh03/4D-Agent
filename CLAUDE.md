# ViSTR-Agent — Spatial-Temporal Reasoning Agent

Design and iterate on a tool-augmented MLLM agent system competing on the ViSTR-Bench
leaderboard (visual spatial-temporal reasoning from continuous video cues, 15 subtasks,
1,340 binary-choice video QA pairs). Reference paper: `references/ViSTR-Bench.pdf`.

## Read first
- Documentation map: `docs/README.md`
- Agent rules (always loaded): `docs/agent/always.md`
- Current work status: `docs/working_logs/active.md`
- Agent system index: `docs/registry/agent_system.md`
- Script registry: `docs/registry/scripts.md`
- Dataset registry: `docs/registry/datasets.md`
- Output registry: `docs/registry/outputs.md`
- Benchmark digest: `docs/knowledge/vistr_bench.md`

## Golden rules
1. Do NOT run expensive/long jobs (GPU inference, large batch evals, model downloads) without explicit user confirmation.
2. Before modifying core scripts, read the relevant rule in `docs/agent/rules/`.
3. Every experiment must write a run log under `docs/working_logs/runs/`.
4. Every code change must include a smoke test command and observed result.
5. Do NOT delete or overwrite files without confirmation — investigate first.
6. Keep `docs/working_logs/active.md` updated when work state changes.
7. Notes (`docs/notes/`) are hypotheses, not facts — do not promote without user approval.
8. Daily reports use topic-based format — see `docs/working_logs/daily/_TEMPLATE.md`.
9. Significant technical decisions must be recorded as ADRs in `docs/adr/`.
10. Never tune on the private held-out set; iterate on the public split only.

## Quick reference
```bash
# Current S2.8 runtime is a Python API; configure configs/agent/s2_8.yaml + its dotenv.
/opt/conda/bin/python -c "from agent.runtime import AgentRunner; print(AgentRunner)"

# Web visualization frontend (Streamlit: Taxonomy / Leaderboard / Sample Browser)
bash scripts/web_frontend.sh                        # http://<host>:8731 (env: /opt/conda/envs/python3.10.13)

# Static visualization (overview dashboard PNG + per-sample replay videos)
bash scripts/visualize.sh                           # overview from outputs/predictions/*.jsonl
bash scripts/visualize.sh --samples <results.jsonl> # per-sample replay videos

# Python: web 前端用 /opt/conda/envs/python3.10.13/bin/python；
# 离线工具/静态渲染用 /opt/conda/bin/python (3.10.13)
```

## Key paths
| Item | Path |
|------|------|
| Agent code | `agent/runtime/` + `agent/pi_ext/vistr_video_tools.ts` |
| Scripts | `scripts/` |
| Benchmark data (public split) | `data/benchmarks/ViSTR-Bench-Public/` → `/mnt/xlab-nas-wm/gaozhe.gz/hf_datasets/` |
| Prediction results (JSONL) | `outputs/predictions/` |
| S2.8 rollout trajectories | YAML `artifacts.trajectory_root` (default `outputs/trajectories/`) |
| Visualization outputs | `data/visualizations/` |
| External tool models | `third_party/` (planned: VGGT, WAFT, SAM2/CoTracker, ...) |
| Reference paper | `references/ViSTR-Bench.pdf` |
