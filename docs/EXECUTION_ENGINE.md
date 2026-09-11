# ForceCode Execution Kernel

ForceCode 7 replaces its ad-hoc “ask until the model stops” behavior with an evidence-oriented execution kernel. The kernel does not expose or store private chain-of-thought. It records only public plans, tool evidence, classified errors, and verification results.

## Processing Flow

```text
User request
  → Planning Engine
  → Token Budget Engine
  → Model and workspace tools
  → Debugging Engine
  → Verification Engine
  → final answer + local run receipt
```

## Architectural Decisions and Rationale

### Local planning before model execution

`PlanningEngine` classifies the task and creates evidence requirements without another API request. This avoids paying input/output tokens merely to restate the user's request. The generated execution contract is intentionally short and visible; it guides the model without pretending to reveal hidden reasoning.

### Evidence steps instead of prose plans

Each `PlanStep` pairs an objective with required evidence. Models can confidently claim success without modifying or testing anything, so completion is tied to observable tool results rather than narrative quality.

### Phase-specific token budgets

`TokenBudgetEngine` allocates separate context, planning, debugging, verification, and output budgets. A single maximum-token setting cannot distinguish useful implementation output from repeated history or verbose recovery text. Efficiency mode reduces these budgets deterministically; it does not silently weaken safety gates.

### Structured failure classification

`DebuggingEngine` maps errors into path, tool-contract, authentication, rate-limit, timeout, encoding, syntax, permission, or unknown categories. Stable hashes deduplicate equivalent failures. Retryability belongs to the category, preventing blind retries of invalid paths, credentials, or schemas while still allowing bounded recovery from transient limits.

### Deterministic verification gates

`VerificationEngine` checks artifact creation, atomic write integrity, post-change inspection, focused checks, multi-file web structure, and final output where applicable. Verification is local because asking the same model “are you sure?” produces correlated confidence rather than independent evidence. One focused recovery turn is permitted; unresolved evidence is reported instead of hidden.

### Append-only observations, compact persistence

Execution state collects tool successes, mutations, checks, and error findings during one run. Only the compact result is saved to `.forcecode/last-run.json`; prompts, secrets, and hidden reasoning are excluded. This gives `/debug` useful evidence without creating an invasive telemetry system. Numeric confidence scoring was removed: pass/fail evidence from the verification gate is the contract, not an opinionated percentage.

### Existing provider transports remain outside the kernel

The kernel coordinates work but does not implement OpenAI, Anthropic, or custom proxy protocols. Keeping transport recovery separate prevents provider quirks from contaminating planning and verification rules and preserves existing API compatibility.

## User Inspection

- `/plan <task>` previews task classification, evidence steps, risks, and token budgets.
- `/debug` shows classified failures and recovery guidance.
- `/engine` explains the active pipeline.

The run receipt is local and covered by the existing `.forcecode/` Git ignore rule.
