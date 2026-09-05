# ViSTR SkillOpt configuration

`vistr_docvqa.yaml` runs the native SkillOpt trainer from
`/workspace/Spatial-Agent/SkillOpt` around the existing S2.8 `AgentRunner`.
Only the Skill text evolves; the Pi harness, prompts outside the Skill, tool
definitions, observer, perception service, and scoring remain fixed.

## Required user inputs

| Field | Meaning |
|---|---|
| `integration.skillopt_root` | Local checkout containing the external `skillopt` Python package. |
| `integration.expected_commit` | Exact upstream commit required at startup. Tracked changes also cause startup to fail. |
| `integration.agent_config` | Existing S2.8 YAML. Its policy provider/model, dotenv, runtime, tools, and artifact root are reused. |
| `dataset.id_file` | JSON array of ViSTR Public question IDs defining the complete experiment pool. |
| `env.skill_init` | Initial evolvable Skill. |
| `env.out_root` | SkillOpt state, patches, generated splits, and evaluation projections. |

The checked-in `vistr_public_ids.json` selects all 670 local Public questions.
Replace it or point `dataset.id_file` at another JSON array to train on a
different subset. Private leaderboard items must never be included.

All relative paths in this profile are resolved relative to
`vistr_docvqa.yaml`. API credentials remain in the dotenv selected by the
referenced agent YAML; the optimizer inherits the policy provider, model ID,
base URL, and key.

## Split behavior

The upstream DocVQA profile consumes an existing `train/val/test` directory.
For ViSTR, this profile follows the requested ratio mode and uses SkillOpt's
generic `SplitDataLoader` implementation unchanged:

```text
random.Random(split_seed).shuffle(selected_items)
counts = largest_remainder(total, train:val:test)
train, val, test = consecutive shuffled slices
```

Defaults are `split_ratio: 2:1:7` and `split_seed: 42`. For the checked-in 670
IDs this produces 134 train, 67 validation, and 469 test items. Generated files
live below `<out_root>/_generated_splits/`. Their manifest records the ID pool,
dataset hashes, split parameters, and SkillOpt commit. Changing any of those
inputs requires a new output directory.

## DocVQA training recipe

The YAML inherits `SkillOpt/configs/docvqa/default.yaml`, including:

- 4 epochs, batch size 40, accumulation 1, seed 42;
- reflection minibatch 8, merge batch 8, analyst workers 16, success and
  failure reflection;
- patch updates with a cosine edit budget from 4 to 2;
- full-validation hard-accuracy gate with strict improvement;
- slow update enabled with 20 samples and mixed longitudinal pairs;
- meta skill enabled and skill-aware reflection disabled;
- final evaluation on the full test split.

DocVQA target-runtime knobs do not replace the 4D runtime. Pi remains a
multi-turn tool agent, uses the model token limits and four rollout workers in
`s2_8.yaml`, and produces video-tool observations rather than `image_detail`
requests. SkillOpt's optimizer output cap is 16,384 tokens. DeepSeek ignores
the OpenAI-specific `reasoning_effort` field; thinking is determined by the
inherited model itself.

## Commands

Preflight and offline tests do not call an API:

```bash
/opt/conda/bin/python agent/tests/test_skillopt_bridge.py
/opt/conda/bin/python agent/tests/test_runtime.py
```

One real training-step smoke uses two loaded train items and one validation
item, and disables final test, slow update, and meta skill:

```bash
/opt/conda/bin/python -u -m agent.skillopt \
  --config configs/skillopt/vistr_docvqa.yaml \
  --smoke
```

The formal DocVQA-aligned run is:

```bash
/opt/conda/bin/python -u -m agent.skillopt \
  --config configs/skillopt/vistr_docvqa.yaml
```

Use repeatable structured overrides only when intentionally creating a new
experiment recipe:

```bash
... --set env.out_root=../../outputs/skillopt/my_run \
    --set train.num_epochs=1
```

## ViSTR versus DocVQA 100-item pilot

The comparison profiles use a training batch size of 5. With 20 train items
and four epochs, both benchmarks receive 16 Fast Update Steps and the same
cosine edit-budget schedule:

```text
4, 4, 4, 4, 4, 3, 3, 3, 3, 3, 2, 2, 2, 2, 2, 2
```

Prepare the fixed seed-43 data first:

```bash
/opt/conda/bin/python -u -m agent.skillopt.prepare_comparison \
  --config configs/skillopt/comparison_100.yaml
```

This samples 100 ViSTR Public questions and 100 DocVQA questions from the
SkillOpt-released 534-ID validation pool, then creates 20/10/70 train/val/test
splits. Seed 43 is the first seed at or above 42 whose uniform ViSTR sample
covers all 15 tasks. DocVQA contains 100 distinct images with gold answers;
the official answerless test split is not used.

Run the two conditions with:

```bash
/opt/conda/bin/python -u -m agent.skillopt \
  --config configs/skillopt/vistr_comparison_100.yaml

/opt/conda/bin/python -u -m agent.skillopt \
  --config configs/skillopt/docvqa_comparison_100.yaml
```

Both use the DeepSeek target and optimizer selected by `s2_8.yaml`. ViSTR keeps
the S2.8 Pi/tool agent and its seed Skill; DocVQA keeps the upstream one-turn
agent and DocVQA seed Skill.

After both runs finish:

```bash
/opt/conda/bin/python -u -m agent.skillopt.compare_runs \
  --vistr outputs/skillopt/comparison_seed43/vistr \
  --docvqa outputs/skillopt/comparison_seed43/docvqa \
  --out outputs/skillopt/comparison_seed43/report
```

The primary metric is the number of Fast Update Steps accepted by the strict
validation gate. Force-accepted slow updates are reported separately. This is
a single-seed system-level pilot, not a causal test of answer-space size.

### Fengyuan GPT-5.5 formal profiles

The handover run uses the `_gpt55.yaml` profiles and a separate output root:

```bash
.venv/bin/python -u -m agent.skillopt \
  --config configs/skillopt/vistr_comparison_100_gpt55.yaml

.venv/bin/python -u -m agent.skillopt \
  --config configs/skillopt/docvqa_comparison_100_gpt55.yaml
```

Both inherit `gpt-5.5`, medium reasoning, and the official OpenAI endpoint from
`configs/agent/s2_8_gpt55.yaml`. SkillOpt's target and optimizer remain
`inherit_policy`; the integration routes official OpenAI to SkillOpt's native
`openai_chat` backend, while DeepSeek/OpenRouter continue through the generic
compatible backend. The DocVQA-aligned `max_completion_tokens` remains 16,384;
the Pi Policy advertises a 65,536-token per-response ceiling.

Run the paired smoke first by adding `--smoke` to each command. After two
complete formal histories contain 16 Fast Update Steps each, generate the
handover report:

```bash
.venv/bin/python -u -m agent.skillopt.compare_runs \
  --vistr outputs/skillopt/comparison_seed43_gpt55/vistr \
  --docvqa outputs/skillopt/comparison_seed43_gpt55/docvqa \
  --out outputs/skillopt/comparison_seed43_gpt55/report \
  --expected-steps 16
```

The reported Effective Update Rate is:

```text
count(action in {accept, accept_new_best}) / len(history.json)
```

`reject`, `skip_*`, and all other Fast-step actions remain in the denominator.
Slow `force_accept` actions are outside both numerator and denominator. A run
with fewer than 16 history entries is partial and cannot support the final
comparison.
