---
status: completed
date: 2026-09-05
scope: notebook-smoke
---

# Notebook smoke stdin workaround

## Diagnosis

Pi 0.84.0 treats non-TTY stdin as piped input and waits for EOF before processing
the CLI prompt. Jupyter keeps its stdin socket open, while `AgentRunner` did not
override the child's stdin. The first `smoke` attempt therefore timed out after
600 seconds without creating a Pi session, and the configured retry started the
same blocked flow again.

## Change

Updated the second cell in `tmp.ipynb` to:

- temporarily patch subprocess calls made during the rollout with
  `stdin=subprocess.DEVNULL`;
- restore the original subprocess function after the rollout;
- use a timestamped run ID to avoid mixing attempts with the failed `smoke` run;
- print an elapsed/attempt/session heartbeat every 10 seconds.

The reusable runtime itself is unchanged.

## Verification

- Notebook JSON and nbformat validation passed.
- Both code cells compile.
- An offline child process read stdin to immediate EOF and exited successfully.
- The original `subprocess.run` was restored after the patch context.
- `git diff --check` passed.

No provider call or benchmark run was made by this change. The user's previously
started notebook cell must be interrupted before executing the replacement cell.
