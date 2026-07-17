# Changelog

All notable changes to ForgeCode are documented here. The project follows semantic versioning where practical.

## [7.1.0] - 2026-07-18

### Fixed

- Keep streaming transport active for subagents, one-shot requests, and tool follow-up rounds even when no live terminal renderer is attached, preventing the configured 30-second socket timeout from silently returning.
- Detect truncated or invalid tool-call JSON before executing `write_file` or `write_files`, return a precise tool error, normalize provider history, and retry with the full configured output budget.
- Remove the duplicate legacy efficiency cap that could reduce the Execution Kernel's file-generation budget from 4,096 to 2,048 tokens.
- Mark rejected or Smart Autopilot-blocked writes as errors instead of successful mutations.
- Verify that every successful write result corresponds to a real file before accepting mutation evidence.

### Changed

- Artifact-producing build, debug, and refactor tasks now receive up to 6,144 tokens in balanced mode and 4,096 in maximum-efficiency mode, bounded by the user's `max_tokens` setting.
- Streaming remains the recommended default; unsupported SSE transports safely fall back to unlimited interactive JSON reads while Ctrl+C cancellation remains available.

## [7.0.1] - 2026-07-17

### Fixed

- Prevent long-running streamed generations from failing with `The read operation timed out` when a provider silently falls back from SSE streaming to a normal JSON response.
- Keep explicit non-streaming requests and health checks bounded by the configured timeout while preserving Ctrl+C cancellation for unlimited interactive generations.

## [7.0.0] - 2026-07-17

### Changed

- Replaced the ad-hoc reasoning/completion guards with a modular Execution Kernel.
- Every request now receives a local evidence-oriented execution plan and phase-specific token budget without an extra planning API call.
- Tool and API failures are classified by a Debugging Engine with stable signatures, retry guidance, and repeated-failure detection.
- Completion is evaluated by deterministic verification gates rather than model confidence alone.
- Each run receives an evidence-based confidence score and a local `.forgecode/last-run.json` receipt containing no private chain-of-thought.

### Added

- `/plan`, `/debug`, `/confidence`, and `/engine` inspection commands.
- Public execution contracts, missing-evidence warnings, and architecture documentation for the new engine.

## [6.7.0] - 2026-07-17

### Added

- ForceContext v2 with explicit initialization, user/project/session memory layers, provenance, confidence, expiry, and local privacy controls.
- A staged Context Engine for intent analysis, candidate retrieval, secret filtering, token budgeting, compilation, and per-request Context Receipts.
- Incremental project scanning with `.forceignore`, file metadata caching, and a 20,000-file default ceiling.
- Response Analyzer that records important decisions as suggestions and promotes only verified, artifact-backed outcomes.
- Interactive and standalone `force-context-*` commands, memory preview/edit/delete/disable/export/wipe controls, and cross-process write locks.

## [6.6.0] - 2026-07-17

### Added

- English and Turkish terminal interface support.
- First-run language selection before provider setup.
- Persistent `/language en|tr` command and matching default response language.
- English help, banner, status bar, control bar, streaming state, setup, and common command messages.

## [6.5.0] - 2026-07-17

### Fixed

- Reject empty, root, and directory targets in file tools.
- Write large files in verified UTF-8 chunks and atomically replace targets.
- Preserve existing targets when a write is interrupted.
- Safely adapt spaced paths and Bash-style command chains for Windows PowerShell.
- Treat non-zero command exits as tool failures so the model can correct them.
- Store Windows user configuration under `%LOCALAPPDATA%\ForgeCode` and copy legacy settings without deleting them.
- Make the global launcher independent of the source checkout location.

## [6.4.0] - 2026-07-14

### Fixed

- Execute strict read-only `type`, `cat`, and `Get-Content` file views through the internal UTF-8 reader.
- Prevent repeated shell-read and safety-classification loops.
- Reset transient streaming drafts between tool rounds.

## [6.3.1]

### Fixed

- Prevent Windows code-page decoder-thread crashes and secondary `NoneType` output failures.

## [6.3.0]

### Added

- Persistent redacted diagnostics and allowlisted AI-managed performance settings.

## [6.2.0]

### Added

- Smart Autopilot with AI risk assessment and a deterministic local safety floor.
