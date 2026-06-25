# Safety Policy

Generated candidate programs are untrusted code. Treat each evaluation as hostile until proven otherwise.

## Required Candidate Isolation

Run each candidate with:

- No network by default.
- Non-root user.
- Read-only source checkout.
- Separate temporary working directory.
- No host credentials, API keys, SSH keys, cloud tokens, or browser cookies.
- No Docker socket or host control sockets.
- CPU, memory, process, file size, output size, and wall-time limits.
- Hidden tests mounted or reachable only by evaluator code.
- Fresh environment per candidate or a documented cache invalidation policy.

Codex sandboxing is useful, but it is not a substitute for evaluator-worker isolation. The runtime must enforce candidate-level boundaries even when Codex itself is already sandboxed.

The bundled local runtime is an MVP harness, not a production sandbox. It runs evaluators inside copied candidate work directories with a reduced environment and timeout enforcement, but it does not provide container-level network, memory, process, or filesystem isolation. Use containerized or remote workers before evaluating hostile or high-risk candidates.

## Approval Boundaries

Ask the user before:

- Executing generated code for the first time in a repository.
- Enabling network.
- Increasing file-system access outside `.alphaevolve/`.
- Passing credentials or private data into evaluator workers.
- Sending API credentials to custom model endpoints outside the runtime's default provider allowlist.
- Running long or costly experiments.
- Applying a champion patch to source files.

## Static Review Before Execution

Before evaluating candidates in a weak sandbox, scan for:

- Network imports or shell commands.
- File traversal, environment reads, and credential paths.
- Writes outside the candidate workspace.
- Long-running loops or process spawning.
- Test discovery tricks.

Reject or quarantine suspicious candidates. Do not feed hidden-test details back into mutation prompts.

## API Credential Boundary

TaskSpec files are experiment inputs, not trusted authority for secret routing. Default runtime behavior should:

- Keep generated patches, prompts, reports, and databases under `.alphaevolve/`.
- Allow HTTP model endpoints only for loopback development servers.
- Allow external model calls only to known provider hosts unless the launch command explicitly enables a custom API base.
- Send external API calls only with provider-default key names or deliberately scoped variables such as `AEVOLVE_*_API_KEY`.
- Never expose API keys, hidden tests, or host credentials to candidate worktrees or agent prompt files.

## Final Champion Review

Evaluate the final candidate outside the selection loop with fresh seeds or holdout cases. Check correctness first, then performance. Report remaining risks clearly if isolation, hidden tests, or measurement quality were incomplete.
