# ForceFlow Architecture

ForceFlow is ForceCode's persistent sequential execution engine. It converts a large objective into bounded tasks, runs only the first unresolved item, and advances after deterministic evidence gates pass.

## Lifecycle

1. A normal project request automatically asks the selected AI for a compact JSON task plan without tools or hidden reasoning. Simple chat and explicit Plan mode bypass ForceFlow.
2. Tasks are stored in `.forgecode/tasks.json` with an ID, the root objective, acceptance criterion, status, attempts, repair attempts, changed files, confidence, and missing evidence.
3. The active item runs through the normal Agent and Execution Kernel. Later items are included only as queue state, never as permission to start early.
4. ForceFlow verifies changed paths as non-empty UTF-8 artifacts and records compact hashes. When the only missing evidence is a focused check, it invokes project test auto-detection.
5. A verified item becomes `completed`. Missing evidence starts bounded root-cause-driven repair rounds; only an exhausted repair budget becomes `failed` and blocks the chain.
6. Framework-free website objectives receive a final model-independent quality audit. If it finds structural, responsive, accessibility, placeholder, or asset-integrity failures, ForceFlow creates an internal repair item and audits the result again. Detected React/Next/Vue/Svelte-style projects retain their framework and use its native test or build command instead.

## States and recovery

Valid states are `pending`, `running`, `paused`, `failed`, `completed`, and `skipped`. A process restart converts stale `running` state to `paused`, preserving attempts and evidence. API failures and verification gaps are retried inside the current run. Each repair prompt includes the root objective, current artifacts, last result, and exact missing evidence so the model diagnoses rather than repeats. The next normal prompt can still resume an exhausted or interrupted item as fresh recovery guidance. ForceFlow never skips uncertainty automatically and exposes no manual queue command surface.

Unattended recovery does not weaken approvals. Safe project-scoped work can continue under the configured Autopilot/Smart Autopilot policy, while destructive, credential-related, ambiguous, or otherwise approval-requiring actions still stop for the user.

## Tooling

- `apply_edits` validates every exact replacement before writing. Multiple edits to the same file are applied in order. A write failure triggers best-effort rollback of files already changed by that transaction.
- `verify_artifacts` checks project-relative files without returning their full contents. It reports byte size, line count, and a truncated SHA-256 digest, and can assert required text.
- `web_quality_check` deterministically scores static sites and reports actionable blockers for structure, responsive CSS, accessibility basics, placeholders, duplicate IDs, and local asset integrity.

Both tools stay inside the existing WorkspaceTools and ForceSandbox boundaries. They inherit write approvals, Smart Autopilot decisions, path traversal protection, secret redaction, and sandbox transfer gates.

## Limits

`flow_max_tasks` defaults to 12 (maximum 50), `flow_max_rounds` defaults to 3 (maximum 10), and `flow_repair_rounds` defaults to 3 (maximum 10; zero disables in-run repair). `flow_quality_gate` is enabled by default. These limits prevent infinite retry loops while allowing ForceCode to be left working unattended.
