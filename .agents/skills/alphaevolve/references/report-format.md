# Report Format

Use this structure when summarizing a run for the user.

## Required Sections

1. Objective and constraints.
2. Baseline metrics.
3. Best champion metrics.
4. Improvement summary.
5. Validation status.
6. Candidate lineage.
7. Proposed diff or file changes.
8. Cost and runtime budget consumed.
9. Safety and evaluator risks.
10. Recommended next step.

## Champion Summary

Include:

- `candidate_id`
- parent IDs
- model or adapter used
- patch source, such as local patch file or model-generated diff
- patch mode
- metrics table
- evaluator commands used
- number of repetitions
- hidden or holdout result, if available
- significance threshold and whether it was met

## Risk Language

Be explicit about gaps:

- "No hidden evaluator was configured."
- "Performance improvement is within observed noise."
- "Candidate isolation did not block network."
- "Champion has not been manually reviewed."
- "The patch is proposed but not applied."

## Do Not Claim

Do not claim a general algorithmic discovery if the evidence only shows improvement on a local evaluator. Do not claim a production speedup without production-like validation. Do not hide failed validation attempts.
