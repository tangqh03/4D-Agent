# 4D Video Reasoning Skill

## Evidence-First Observation

- Inspect actual video frames before deciding. Treat `index_video` captions as navigation hints, not final visual evidence.
- Start with a coarse temporal view, then narrow to the shortest interval that contains the answer-relevant change.
- For every motion or change claim, compare at least two timestamped observations in the correct temporal order.

## Context-Preserving Inspection

- Use `semantic_crop` when the target is hard to localize; describe the target with a short English noun phrase.
- Prefer a video-segment crop when the answer depends on local motion. Keep enough surrounding context to preserve interaction partners and spatial references.
- If grounding or cropping appears unreliable, return to global frames or use an explicit `read_crop` region instead of trusting the failed localization.

## Decision Discipline

- Separate directly observed facts from predicted outcomes. Base the choice on the visual cue that best distinguishes the given options.
- Stop gathering evidence once the decisive cue has been checked; repeated views without a new question do not strengthen the conclusion.
- Return exactly one provided option in the required `<answer>exact option text</answer>` format.
