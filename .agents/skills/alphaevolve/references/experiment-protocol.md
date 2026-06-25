# Experiment Protocol

Use this protocol to make runs reproducible, interruptible, and reviewable.

## Run Lifecycle

1. `init`: create `.alphaevolve/task.yaml` and run directories.
2. `validate`: check TaskSpec, evaluator command shape, and baseline behavior.
3. `run`: start the runtime with fixed budgets.
4. `status`: read structured status such as `status.json` or runtime API output.
5. `pause` or `stop`: preserve database and checkpoints.
6. `resume`: continue from checkpoint with the same TaskSpec unless the user explicitly changes it.
7. `review`: independently validate champion candidates.
8. `export`: write a report and proposed patch.

## Runtime State

Prefer this run layout:

```text
.alphaevolve/
  task.yaml
  runs/
    <run-id>/
      run.db
      task.yaml
      status.json
      candidates/
      patches/
      logs/
      checkpoints/
      report/
```

The runtime should write structured status:

```json
{
  "run_id": "run-20260625-001",
  "state": "running",
  "evaluated": 117,
  "queued": 21,
  "best_candidate": "c-00103",
  "best_metrics": {
    "latency_ms": 12.91
  },
  "stop_reason": null
}
```

## Search Policy Defaults

For MVP runs, prefer:

- Local patch files passed through `--patch` or `--patch-dir` before enabling live model generation.
- API-generated patches through `run --generate N` only after the user approves model spend and provides the key through the configured environment variable.
- Codex/Claude worker patches through `agent-prompts --count N`; workers must return patch text rather than editing the repository directly.
- `top-k` elite retention.
- Diversity sampling across metric profiles and changed files.
- Failed-case summaries as negative feedback, without hidden-test leakage.
- Evaluation cascade: static checks, public correctness, public performance, hidden correctness, final validation.
- Checkpoint after every database update.

Add MAP-Elites, islands, Pareto ranking, model routing, and prompt evolution only after the simple loop works on a cheap benchmark.

## Measurement Rules

- Compare against a baseline captured in the same environment.
- Use repeated runs for noisy metrics.
- Track median, best, worst, and variability.
- Define the minimum meaningful improvement before launch.
- Avoid accepting champions that only improve within measurement noise.
