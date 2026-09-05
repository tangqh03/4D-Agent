---
status: accepted
date: 2026-09-05
scope: agent-runtime
---

# ADR: Self-contained S2.8 runtime with an evolvable Skill

## Context

The S2.8 flow mixed ViSTR loading, Pi configuration, process management, answer parsing, and output persistence in one evaluation script. Policy and observer credentials depended on `~/.pi/agent/models.json`, Pi sessions landed in implicit user directories, and there was no stable rollout boundary for future SkillOpt integration.

## Decision

Provide a Python `AgentRunner` configured by one YAML file and its selected dotenv file. Keep the Pi harness and the named S2.8 Tool Bundle fixed, expose only Agent Items and Skill content to rollouts, generate Pi provider configuration in a temporary mode-0600 directory, manage the configured local Perception Service for the runner lifetime, and persist every Attempt as Pi JSONL, Pi-rendered HTML, addressable images, and a compact reflection conversation.

The complete Skill is appended to Pi's system prompt, matching SkillOpt DocVQA's direct-injection semantics. This deliberately accepts lower prompt-cache reuse when candidate Skills change. Tool definitions, task input, and final-answer protocol remain outside the evolvable Skill.

## Rationale

This separates user configuration from credentials, removes hidden global state, preserves the best-performing S2.8 observation behavior, and gives a future SkillOpt adapter the scored records and conversations it needs without coupling the runtime to SkillOpt today. A named Tool Bundle prevents arbitrary extension paths from becoming part of the optimization surface.

## Consequences

- The first version supports only OpenAI Chat Completions-compatible providers, Pi, ViSTR, and the S2.8 Tool Bundle.
- `context_window: -1` and `max_tokens: -1` delegate to Pi defaults rather than probing provider limits.
- Managed perception configuration is persistent authorization to start the specified local GPU service.
- Old V4 and evidence-closure code remains available for historical reproduction but is not part of the active runtime.
