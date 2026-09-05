# S2.8 agent configuration reference

`s2_8.yaml` is the supported runtime configuration for the current S2.8
ViSTR agent. It contains non-secret choices and paths. The dotenv selected by
`env_file` contains API URLs, keys, private headers, and the Perception Service
URL.

All relative paths in the YAML are resolved from `configs/agent/`, not from the
shell's working directory. Unknown fields fail validation instead of being
silently ignored.

## Default DeepSeek configuration

The checked-in YAML uses DeepSeek's OpenAI-compatible endpoint and its vision
model. The model must accept images because Pi sends observation-tool images
back to the Policy, and the inherited Observer also receives images.

```yaml
providers:
  deepseek:
    api: openai-completions
    base_url_env: POLICY_API_BASE_URL
    api_key_env: POLICY_API_KEY

models:
  policy:
    provider: deepseek
    id: deepseek-v4-flash-vision-exp
    name: DeepSeek V4 Flash Vision Experimental
    reasoning: true
    context_window: 1000000
    max_tokens: 32768
  observer:
    inherit: policy
```

Use this dotenv:

```dotenv
POLICY_API_BASE_URL=https://api.deepseek.com
POLICY_API_KEY=<your DeepSeek API key>
PERCEPTION_URL=http://127.0.0.1:7876
```

Use the official Base URL without `/chat/completions`; the runtime and Observer
extension append that path. The `deepseek` provider alias also lets Pi select
its DeepSeek Chat Completions compatibility behavior. DeepSeek Observer calls
to `index_video` and multi-candidate `semantic_crop` explicitly send
`thinking: {type: disabled}`; Policy thinking remains controlled by Pi.

References: [DeepSeek first API call](https://api-docs.deepseek.com/zh-cn/),
[vision input](https://api-docs.deepseek.com/zh-cn/guides/vision), and
[thinking mode](https://api-docs.deepseek.com/zh-cn/guides/thinking_mode).

## OpenRouter configuration

Keep the rest of `s2_8.yaml` unchanged and replace the provider/model sections.
The example model ID is illustrative; choose an OpenRouter model that supports
both image input and Tool Calls.

```yaml
providers:
  openrouter:
    api: openai-completions
    base_url_env: POLICY_API_BASE_URL
    api_key_env: POLICY_API_KEY

models:
  policy:
    provider: openrouter
    id: google/gemini-3.8-flash
    name: Gemini 3.8 Flash
    reasoning: true
    context_window: 1048576
    max_tokens: 32768
  observer:
    inherit: policy
```

Use this dotenv:

```dotenv
POLICY_API_BASE_URL=https://openrouter.ai/api/v1
POLICY_API_KEY=<your OpenRouter API key>
PERCEPTION_URL=http://127.0.0.1:7876
```

The `openrouter` provider alias activates Pi's OpenRouter compatibility path.
Observer request bodies retain their existing OpenAI-compatible shape and do
not receive DeepSeek's `thinking` field.

Optional OpenRouter headers can be sourced from the dotenv:

```yaml
providers:
  openrouter:
    api: openai-completions
    base_url_env: POLICY_API_BASE_URL
    api_key_env: POLICY_API_KEY
    headers_env:
      HTTP-Referer: OPENROUTER_HTTP_REFERER
      X-Title: OPENROUTER_X_TITLE
```

If `headers_env` is present, every referenced variable must be non-empty in the
selected dotenv.

## Separate Policy and Observer providers

Declare both providers and fully specify `models.observer` instead of using
`inherit`. Both models must accept images. This example uses DeepSeek for the
Policy and OpenRouter for the Observer:

```yaml
providers:
  deepseek:
    api: openai-completions
    base_url_env: DEEPSEEK_API_BASE_URL
    api_key_env: DEEPSEEK_API_KEY
  openrouter:
    api: openai-completions
    base_url_env: OPENROUTER_API_BASE_URL
    api_key_env: OPENROUTER_API_KEY

models:
  policy:
    provider: deepseek
    id: deepseek-v4-flash-vision-exp
    name: DeepSeek V4 Flash Vision Experimental
    reasoning: true
    context_window: 1000000
    max_tokens: 32768
  observer:
    provider: openrouter
    id: <OpenRouter vision model ID>
    name: <display name>
    reasoning: false
    context_window: <model context window>
    max_tokens: <model output limit>
```

```dotenv
DEEPSEEK_API_BASE_URL=https://api.deepseek.com
DEEPSEEK_API_KEY=<your DeepSeek API key>
OPENROUTER_API_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_API_KEY=<your OpenRouter API key>
PERCEPTION_URL=http://127.0.0.1:7876
```

The Observer's `reasoning` flag describes the model to Pi. The fixed Observer
subcalls choose their own small output budgets; the DeepSeek-host-specific
thinking override is applied by the extension.

## OpenAI GPT-5.5 handover configuration

`s2_8_gpt55.yaml` is the clean-machine profile for Fengyuan's experiment. It
uses the official OpenAI endpoint, GPT-5.5, and medium reasoning for the Pi
Policy and inherited Observer:

```yaml
providers:
  openai:
    api: openai-completions
    base_url_env: POLICY_API_BASE_URL
    api_key_env: POLICY_API_KEY

models:
  policy:
    provider: openai
    id: gpt-5.5
    reasoning: true
    thinking_level: medium
    context_window: 1050000
    max_tokens: 65536
  observer:
    inherit: policy
```

Create the untracked dotenv with:

```bash
cp .env.gpt55.example .env.gpt55
```

The OpenAI observer path sends `max_completion_tokens` and
`reasoning_effort: medium`, and omits `temperature`. SkillOpt uses its native
`openai_chat` backend with the same model and reasoning setting. DeepSeek and
OpenRouter retain their existing request shapes.

OpenAI documents GPT-5.5 as supporting image input, Chat Completions, function
calling, medium reasoning, a 1,050,000-token context window, and up to 128,000
output tokens:
<https://developers.openai.com/api/docs/models/gpt-5.5>.

## Field reference

### Top level

| Field | Meaning |
|---|---|
| `version` | Configuration schema version. The current runtime requires `1`. |
| `env_file` | Dotenv file selected by this YAML. Relative paths resolve from the YAML directory. |
| `providers` | Named OpenAI-compatible API connections. Names are referenced by models. |
| `models` | Policy and Observer model definitions. |
| `agent` | Fixed runtime, tools, retry, concurrency, and executable settings. |
| `perception` | Managed GroundingDINO service settings. |
| `dataset` | Dataset adapter and ViSTR data/split locations. |
| `artifacts` | Persistent trajectory output location. |

### `providers.<name>`

| Field | Meaning |
|---|---|
| `api` | API adapter. Schema v1 supports only `openai-completions`. |
| `base_url_env` | Name of the dotenv variable containing the API Base URL. Do not include `/chat/completions`. |
| `api_key_env` | Name of the dotenv variable containing the bearer API key. |
| `headers_env` | Optional mapping from HTTP header names to dotenv variable names. Values are treated as secrets. |

Provider names are local aliases. Prefer `deepseek` and `openrouter` for those
services so Pi can apply the corresponding compatibility behavior even before
examining the URL.

### `models.policy` and `models.observer`

| Field | Meaning |
|---|---|
| `provider` | Key under `providers` used by this model. |
| `id` | Exact model ID sent to the provider. |
| `name` | Human-readable name written into Pi's temporary model catalog. |
| `reasoning` | Marks the model as reasoning-capable for Pi's Policy path. |
| `thinking_level` | Optional Pi reasoning level: `off`, `minimal`, `low`, `medium`, `high`, `xhigh`, or `max`. The runtime passes it through `--thinking`; a non-empty value requires `reasoning: true`. |
| `context_window` | Total model context window in tokens. `-1` delegates the value to Pi defaults. |
| `max_tokens` | Maximum Policy output tokens per request. `-1` delegates to Pi defaults. This does not control Observer subcalls. |
| `inherit: policy` | Observer-only shorthand that reuses the complete Policy model definition and connection. |

`context_window` and `max_tokens` describe provider limits to Pi; they do not
change the upstream model's actual limits. Incorrectly large values can cause
provider errors, while an incorrectly small context window causes premature
compaction.

### `agent`

| Field | Meaning |
|---|---|
| `backend` | Agent backend. Schema v1 supports only `pi`. |
| `tool_bundle` | Closed tool registry. Schema v1 supports only `s2_8_observation`. |
| `seed_skill` | Default evolvable Skill used when `rollout(..., skill_content=None)`. |
| `timeout_s` | Wall-clock timeout for each Pi attempt. |
| `max_attempts` | Maximum attempts after Pi non-zero exit or timeout. |
| `retry_backoff_s` | Base retry delay; later retries multiply it by the retry index. |
| `workers` | Number of Agent Items executed concurrently. Use `1` for the first smoke test. |
| `pi_binary` | Pi executable used for rollouts and native HTML export. |
| `tool_python` | Python executable advertised to the Policy for cv2/numpy analysis. |
| `path_prepend` | Directories prepended to child-process `PATH`, in listed order. |

The fixed Tool Bundle contains Pi `read`, `bash`, `edit`, and `write`, plus
`index_video`, `read_video_sequence`, `read_multiframe`, `read_crop`, and
`semantic_crop`.

### `perception`

| Field | Meaning |
|---|---|
| `mode` | Service ownership policy. Schema v1 supports only `managed`. |
| `endpoint_env` | Dotenv variable containing the Perception Service URL. |
| `python` | Python executable used if the runner must start the service. |
| `script` | GroundingDINO HTTP service entry script. |
| `model_path` | Local GroundingDINO model directory, also passed as `GDINO_PATH`. |
| `visible_devices` | Physical GPU selection passed as `CUDA_VISIBLE_DEVICES`. |
| `eager` | If true, load GroundingDINO before `/health` becomes ready. |
| `startup_timeout_s` | Maximum time to wait for a managed service to become healthy. |

The runner first checks `<PERCEPTION_URL>/health`. It reuses a healthy service
and stops only a service it started itself.

### `dataset`

| Field | Meaning |
|---|---|
| `adapter` | Dataset adapter. Schema v1 supports only `vistr`. |
| `root` | ViSTR-Bench Public root containing `data.json` and video files. |
| `split_config` | Dev/eval ID mapping used by `ViSTRAdapter`. |

### `artifacts`

| Field | Meaning |
|---|---|
| `trajectory_root` | Root for `<run_id>/manifest.json`, `results.jsonl`, native Pi JSONL/HTML, decoded images, and reflection conversations. |

## Validation without an API call

```bash
/opt/conda/bin/python - <<'PY'
from agent.runtime import AgentConfig

config = AgentConfig.from_yaml("configs/agent/s2_8.yaml")
print("Policy:", config.policy.provider, config.policy.id)
print("Observer:", config.observer.provider, config.observer.id)
print("Configuration validated")
PY
```

This checks the schema, dotenv variables, and local paths. It does not prove
that the key has credit or that the remote model is available.
