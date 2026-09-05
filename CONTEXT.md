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

**Optimizer Model**:
The model that reflects on scored Trajectories and proposes Skill edits. It never executes the ViSTR task itself.
_Avoid_: Policy Model, Observer Model

**Candidate Skill**:
A proposed Skill revision that becomes current only after satisfying the validation gate.
_Avoid_: Prompt version, draft prompt

**Selection Split**:
The validation items used to accept or reject a Candidate Skill; they are not used for reflection.
_Avoid_: Test split, training split

**Generated Split Manifest**:
The recorded ID pool, dataset hash, ratio, seed, counts, and SkillOpt version that define one reproducible train/validation/test partition.
_Avoid_: Dataset config, split cache

**Outcome False Positive**:
A Trajectory whose final answer is correct even though its gathered evidence or reasoning does not validly support that answer.
_Avoid_: Lucky answer, false positive

**Fast Update Step**:
One regular SkillOpt Rollout, Reflect, Aggregate, Select, Update, and validation Gate cycle. Epoch-level slow and meta updates are not Fast Update Steps.
_Avoid_: Training iteration, any Skill change

**Effective Update**:
A Fast Update Step whose Candidate Skill is accepted by the validation Gate through strict score improvement.
_Avoid_: Non-empty patch, force-accepted slow update

**Optimization Budget**:
The fixed number of attempted Fast Update Steps and their edit-budget schedule used to compare Skill optimization runs.
_Avoid_: Wall-clock budget, token budget, accepted update count

**Complete Comparison Run**:
A paired ViSTR/DocVQA run in which both histories contain all 16 budgeted Fast
Update Steps under one recorded model and request behavior.
_Avoid_: Smoke test, partial run, one-sided run
