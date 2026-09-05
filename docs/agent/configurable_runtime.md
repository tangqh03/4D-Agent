---
status: active
scope: agent-runtime
last_verified: 2026-09-05
owner: gaozhe
---

# Configurable S2.8 Runtime

The supported runtime is a Python API. It keeps the S2.8 observation tools fixed while moving model, service, data, and artifact settings into YAML.

## Configure

See `configs/agent/README.md` for the complete field reference and copyable
DeepSeek, OpenRouter, and split Policy/Observer recipes.

1. Copy `.env.example` to the dotenv path named by `configs/agent/s2_8.yaml`.
2. Put API URLs, keys, private headers, and the Perception Service URL in that dotenv file.
3. Set model IDs, executable/model paths, dataset paths, concurrency, timeouts, and `trajectory_root` in YAML.
4. Edit `skills/s2_8_initial.md` only when changing the seed observation strategy.

The selected dotenv overrides same-named variables only in child-process environments. The runtime never reads `~/.pi/agent/models.json`.

Observer subcalls to a `deepseek.com` Base URL explicitly send
`thinking: {type: disabled}` so their small caption/selection output budgets are
reserved for committed answers. Other providers do not receive this field.

Selected provider secrets are copied only into a mode-0600 temporary Pi config. The Observer captures its credentials during extension registration and removes them from the environment before the model-callable `bash` tool runs.

## Run from Python

```python
from agent.datasets import ViSTRAdapter
from agent.runtime import AgentRunner

with AgentRunner.from_yaml("configs/agent/s2_8.yaml") as runner:
    items = ViSTRAdapter(runner.config.dataset).load(
        split="dev",
        per_task=1,
    )
    records = runner.rollout(
        items,
        skill_content=None,
        run_id="s28-smoke",
    )
```

`skill_content=None` loads the configured seed Skill. Passing a string applies that candidate Skill to the entire rollout. Reusing a `run_id` resumes completed Agent Items only when the resolved public configuration and Skill hashes match.

## Service behavior

`perception.mode: managed` authorizes the runner to start the configured local GroundingDINO service if `/health` is unavailable. `eager: true` loads the model before rollout. The runner reuses an already healthy service and stops only a process it started.

Do not construct `AgentRunner` outside a `with` block: the context boundary owns temporary Pi configuration and managed service cleanup.
