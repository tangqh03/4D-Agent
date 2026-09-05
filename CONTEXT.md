# 4D-Agent Runtime

The runtime applies a fixed video-observation harness to scored spatial-temporal reasoning items while allowing one natural-language strategy to evolve.

## Language

**Agent Item**:
A single video, question, option set, and optional reference answer presented to the agent.
_Avoid_: Sample, case

**Policy Model**:
The model that chooses observation actions and produces the final answer.
_Avoid_: Main model, target model

**Observer Model**:
A stateless model used for neutral timeline captions and grounding-candidate selection without access to the Agent Item's question or options.
_Avoid_: Caption model, helper model

**Tool Bundle**:
A fixed, named set of tools and their definitions available to the Policy Model.
_Avoid_: Extension list, tool config

**Skill**:
The natural-language observation and reasoning strategy that may change between rollouts while the harness, models, tools, and scoring remain fixed.
_Avoid_: Prompt, system prompt

**Attempt**:
One execution of the Policy Model on one Agent Item, including its complete interaction history and artifacts.
_Avoid_: Retry, session

**Trajectory**:
The ordered actions, observations, messages, and outcome produced by one Attempt.
_Avoid_: Log, transcript

**Rollout**:
A scored execution of one Skill over a collection of Agent Items.
_Avoid_: Evaluation run, batch inference
