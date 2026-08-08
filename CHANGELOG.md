# Changelog

All notable changes to ForgeCode are documented here. The project follows semantic versioning where practical.

## [7.13.0] - 2026-08-08

### Added

- Added a persistent four-terminal fleet: terminal 1 is the permanent manager/design director, while `/terminal add`, `remove`, `task`, and `status` control up to three visible read-only workers with shared reports.
- Added one-call fleet orchestration so an explicitly authorized manager can create/reuse one to three workers, distribute independent tasks, and apply per-worker temporary thinking/output budgets.
- Added dependency-free Chrome DevTools controls and AI tools for opening, reading, clicking, and typing in an isolated local Chrome profile without accessing cookies or browser storage.
- Added a streaming-only YouTube queue with AI-assisted search, ordered playback, startup playback, and official iframe controls. Media is never downloaded and ads are not bypassed.
- Added official CLI subscription bridges for Claude, Codex, Cline, and Gemini. They reuse vendor-managed sign-in without copying tokens or credentials and run in advisory/read-only mode.

### Fixed

- Subscription replies now use chat-style history records instead of corrupting the transcript by extending it with dictionary keys.
- Automatic model recovery now respects a default-on `model_lock`; managers and workers cannot change the provider or model unless the user explicitly selects one.

## [7.12.12] - 2026-08-08

### Fixed

- Fix thinking vs final-answer channel separation in execution kernel: internal auto-repair trace `Hata yakalandı — onarıyorum` and other intent announcements (`yapıyorum`/`inceliyorum`/`düşünüyorum`/`çözüyorum`) now emit only on the transient thinking/trace stream (LiveStreamTerminal + activity) and are never counted as the assistant's final result message. `consume_anthropic_stream` drops `thinking_delta`/`signature_delta` blocks from the answer stream and `Agent.ask` strips the thinking prefix or rejects pure-trace replies, nudging the model to call tools directly. Final output contains only the real answer.

### Added

- Regression test suite `ThinkingChannelRegressionTests` (7 tests) that fails if any thinking/repair trace is promoted to result-message count: pure-trace blocking, prefix stripping, anthropic stream filtering, and `Agent.ask` two-turn promotion check. CI now 347 tests.

## [7.12.11] - 2026-08-08

### Fixed

- Fix thinking vs final-answer channel separation in execution kernel: internal auto-repair trace `Hata yakalandı — onarıyorum` and other intent announcements (`yapıyorum`/`inceliyorum`/`düşünüyorum`/`çözüyorum`) now emit only on the transient thinking/trace stream (LiveStreamTerminal + activity) and are never counted as the assistant's final result message. `consume_anthropic_stream` drops `thinking_delta`/`signature_delta` blocks from the answer stream and `Agent.ask` strips the thinking prefix or rejects pure-trace replies, nudging the model to call tools directly. Final output contains only the real answer.

## [7.12.0] - 2026-08-05

### Added

- Added a dependency-free MCP client with stdio and Streamable HTTP transports, JSON-RPC initialization, dynamic tool discovery, bounded calls, and clean process shutdown.
- Added `/mcp` backend toggling plus `status`, `discover`, `tools`, `use`, `add`, `remove`, and `graph` actions. Project `.mcp.json`, `.vscode/mcp.json`, and `.cursor/mcp.json` entries can be discovered without importing embedded environment secrets.
- The AI can discover, configure, test, activate, remove, or disable MCP servers through `manage_mcp_server` only after the user explicitly requests MCP management.
- Added deterministic natural-language switching for `ForceGraph'a geri geç`, avoiding an unnecessary API call.

### Changed

- MCP and native ForceGraph are now mutually exclusive code-intelligence backends. MCP is enabled only after `initialize` and `tools/list` succeed; successful activation pauses ForceGraph, while failed connections preserve the current backend.
- Active MCP tools are injected into the model schema dynamically and removed again on disconnect. `graph_context` is not offered while MCP is active.

### Security

- MCP subprocesses use argument arrays with `shell=False`, a project-scoped working directory, and a credential-stripped environment. Shell wrappers, remote plaintext HTTP, URL credentials, query tokens, and malformed arguments are rejected.
- MCP descriptions and results are explicitly treated as untrusted data. Saved MCP profiles contain connection metadata only, never API secrets.

### Documentation

- Rebuilt the README as a product-specific visual guide with nine new lightweight SVG diagrams for the feature atlas, execution state machine, context and code-intelligence pipeline, provider control plane, live terminal controls, autonomy and specialist agents, native toolchains, skill security pipeline, and local data boundaries.
- Every major subsystem is now paired with a diagram that explains real behavior rather than decorative generated artwork. All assets are editable vector source, render without external dependencies, and include descriptive README alt text.

## [7.11.2] - 2026-08-05

### Added

- Added `/protocol off [openai|anthropic]` for custom APIs. It disables model/route-based protocol enforcement while retaining an explicit payload codec.

### Fixed

- Raw custom mode now sends directly to the exact `/route` target and never appends a standard API suffix.
- Explicit custom routes no longer force the protocol back on when raw mode is selected.
- Automatic 404 endpoint recovery and successful Anthropic authentication probing no longer overwrite a user-selected `off` protocol state.
- `/endpoint` now reports both the raw protocol state and the payload codec used for the request.
- Scripted stdin for direct Python commands on Windows now bypasses the PowerShell wrapper, preventing intermittent child-input hangs on Python 3.13 CI and real prompt-driven tests.

## [7.11.1] - 2026-08-04

### Fixed

- `/watchdog off` no longer leaves a dead provider connection waiting forever. It still removes the total generation limit, but an independent stall guard now detaches requests that send no first data or stop making progress.
- A stalled request with no visible streamed output is retried once against the same pinned model and unchanged conversation, avoiding an unintended model switch or duplicate visible output.
- Stall thresholds adapt upward from healthy provider latency history, while active long-running streams continue without a total timeout.
- Heartbeat and status text now distinguish unlimited generation time from stuck-connection recovery instead of reporting the misleading `zaman aşımı yok` message.

### Configuration

- Added `stall_guard_enabled`, `stall_first_response_seconds` (120 seconds), `stall_stream_idle_seconds` (180 seconds), and `stall_retry_attempts` (1 by default, 0 to disable retry). Users can raise the limits for unusually slow providers or explicitly disable the guard.

## [7.11.0] - 2026-08-04

### Added

- Added the built-in `skill-scout` meta skill and automatic project enrichment from the skills.sh catalog.
- Added a privacy-preserving local project profiler: only generic technology and task labels are used for discovery; source code, paths, prompts, secrets, and user data are never sent to the catalog.
- Added `/skill scout status|scan|on|off`, local decision receipts, configurable security/contribution gates, per-scan limits, project-wide limits, and scan cooldowns.

### Security

- Every automatic candidate now combines independent skills.sh audit-provider verdicts with deterministic local checks for prompt injection, credential collection/exfiltration, sandbox or approval bypass, destructive host commands, elevated privileges, and unsafe network execution.
- Automatic installation requires a security score strictly above 80/100 and project contribution of at least 60/100. Any critical or partner-failed audit blocks the skill regardless of score.
- Skill Scout installs only standalone UTF-8 `SKILL.md` text into the current project's `.forgecode/skills`; scripts, binaries, hooks, assets, references, and dependencies are not imported or executed.
- Catalog identity mismatches, collisions with existing skills, and skills that depend on unsupported companion files are rejected.

### Efficiency

- Successful scan profiles are cached for 24 hours, accepted skills gain local task triggers for progressive disclosure, and at most the relevant one to three skill bodies continue to enter model context.

## [7.10.1] - 2026-08-04

### Fixed

- ForceFlow artifact verification now accepts non-empty compiled and media artifacts such as `.class`, JAR, EXE, DLL, image, font, and database files as binary hash evidence instead of incorrectly requiring UTF-8 text.
- Large compiler output sets are verified in bounded batches rather than failing the 50-path tool limit.
- Temporary `.forceclient-check` compiler output is excluded from project change tracking and verified sandbox transfer, while real source changes and final toolchain evidence remain checked.
- Artifact verification failures now become normal ForceFlow evidence failures instead of escaping as an unhandled `ValueError`.

## [7.10.0] - 2026-08-04

### Added

- Added VibeCode, an opt-in overnight autonomy mode driven by one broad product objective through `/vibe <goal>` or an armed next prompt with `/vibe on`.
- Added architecture-first task planning, task-by-task persistent checkpoints, transcript compaction between tasks, deterministic project-wide gates, and an independent read-only final acceptance review.
- Added crash-safe `.forgecode/vibe-session.json` state, `/vibe status|resume|stop|hours`, and a human-readable `.forgecode/vibe-report.md` receipt.

### Reliability

- Long VibeCode builds receive an independent command budget of up to 1,200 seconds by default while model requests use patient first-response, idle, and total watchdog limits.
- Transient API/reviewer failures use capped exponential backoff without consuming product-quality review cycles; repeated local task failures can be deferred so unrelated work continues.
- Interrupted sessions recover as paused rather than completed, and no run reports success until both local verification and an independent score of at least 80/100 pass.

### Security

- Unattended mutation requires an active ForceSandbox. Safe isolated project actions need no overnight prompt, while deterministic destructive commands and credential-sensitive paths remain blocked.
- Existing verified transfer, snapshot, conflict detection, secret exclusion, and rollback controls remain mandatory.

## [7.9.0] - 2026-08-03

### Added

- Added the guarded `project_toolchain` model tool for project inspection, deterministic multi-file scaffolding, native builds, focused tests, and packaging.
- Added first-class C++/CMake executable, .NET single-file executable, Java executable JAR, and Minecraft Paper plugin scaffolds.
- Added automatic toolchain detection and native command selection for CMake, .NET, Maven/Gradle (including wrappers), Cargo, Go, Node, and Python.
- Added built-in `native-cpp`, `dotnet-application`, `java-jar`, and `minecraft-paper-plugin` skills with progressive task matching.

### Reliability

- Compiled build/package operations now require a real non-empty executable or JAR artifact after a successful command; a zero exit code alone is no longer sufficient evidence.
- CMake and system-Gradle projects are now included in automatic project testing.
- Scaffold writes use one approval, UTF-8 verification, overwrite protection, and rollback if any file fails.

## [7.8.0] - 2026-08-02

### Added

- Added a dependency-free, local-first Agent Skills engine compatible with the portable `SKILL.md` directory format and YAML frontmatter.
- Added progressive disclosure: ForgeCode scores enabled skills against each user request and injects only the one to three most relevant instruction bodies according to the efficiency mode.
- Added four built-in skills for root-cause debugging, frontend quality, evidence-driven project audits, and release readiness.
- Added `/skills` plus `/skill show|discover|install|update|enable|disable|remove`, along with `list_skills` and guarded `manage_skill` AI tools.
- Added safe GitHub installation from repository, tree/blob, raw `SKILL.md`, and `owner/repo` sources. Imports accept only bounded UTF-8 instructions; scripts and binaries are never downloaded or executed.
- Added user-wide and project-scoped skills, deterministic precedence, persistent enable/disable state, and natural-language skill management authorization.

### Security

- Remote skill mutation requires an explicit skill-management request. Skill instructions are labeled lower-priority and cannot override user intent, sandbox boundaries, approvals, or system safety.

## [7.7.3] - 2026-08-02

### Changed

- Automatic model switching is now disabled by default. Provider, tool, route, model-unavailable, and transient API errors preserve the model explicitly selected by the user.
- Added the typed `auto_model_switch` setting. Users can opt in with `/set auto_model_switch true` and turn it off again without reconnecting.
- When switching is disabled, diagnostics state that the selected model was preserved instead of silently probing alternatives.

## [7.7.2] - 2026-08-02

### Changed

- Removed ForceSandbox's default 200 MB aggregate project and verified-transfer ceiling. `sandbox_max_transfer_mb: 0` now means unlimited while a positive value still enables an optional user-defined cap.
- Existing configurations that still contain the former 200 MB default are migrated automatically to unlimited mode; deliberately customized limits are preserved.
- Kept the independent per-file size guard, secret exclusions, path isolation, snapshots, conflict detection, verification gates, and atomic rollback unchanged.

## [7.7.1] - 2026-08-01

### Performance

- Cohesive one-part project requests now use an immediate local one-task ForceFlow plan instead of waiting for a separate remote planner. Remote decomposition is reserved for genuinely sequential, multi-domain, bulleted, or very large objectives.
- AI-generated plans are capped adaptively at six tasks for normal objectives and eight for very large objectives, preventing simple site requests from expanding into 10-12 API-heavy steps.
- ForceFlow tasks no longer run a second automatic remote orchestrator before every item. The main model retains `delegate_task` and can still start a specialist when it provides real value.
- Optional planner, orchestrator, and safety preflights now have a separate 12-second budget even when `/watchdog off` keeps the main generation unlimited. Optional subagents also remain bounded by `subagent_timeout_seconds`.
- Smart Autopilot no longer calls a remote safety model for ordinary writes already isolated inside ForceSandbox; deterministic safety checks and verified transfer gates remain active.

### Fixed

- Existing over-planned cohesive ForceFlow chains are collapsed on resume, so v7.7.0 queues with many untouched website subtasks do not keep wasting requests after upgrading.
- Frontend quality and automatic recovery remain enabled on the fast path; the performance fix removes duplicate coordination rather than verification.

## [7.7.0] - 2026-08-01

### Added

- Added ForceFlow, a persistent ordered task engine that automatically detects real project work, lets the selected AI create the task plan, and advances only after the current task passes artifact and Execution Kernel verification.
- Normal prompts now invoke ForceFlow automatically when task decomposition adds value; one-step work remains one task and simple conversation avoids the planner entirely.
- Added crash-safe task states in `.forgecode/tasks.json`; interrupted work resumes as paused instead of being lost or falsely marked complete.
- Added the `apply_edits` model tool for validated multi-file exact replacements with rollback on write failure.
- Added the `verify_artifacts` model tool for compact non-empty UTF-8, required-text, line-count, size, and SHA-256 evidence.
- Added evidence-guided autonomous repair rounds. ForceFlow now carries the root objective, failures, and missing verification into a different recovery approach without waiting for another user prompt.
- Added the deterministic `web_quality_check` tool and final site quality gate for responsive multi-file structure, semantic/accessibility basics, placeholder detection, duplicate IDs, and local asset integrity.

### Changed

- Removed the manual `/flow`, `/task`, `/tasks`, and `/batch` command surface. Sequential planning, retry, recovery, and progression are internal AI-managed behavior.
- The dashboard and `/status` now expose open, completed, and failed sequential task counts.
- ForceFlow automatically runs the project's focused test command when a changed task is otherwise missing only post-change check evidence.
- Every generated subtask now retains the original user objective, preventing website quality requirements from disappearing during task decomposition.
- Failed final website audits automatically create a bounded internal repair task and are rechecked before ForgeCode can report completion.

### Security

- A failed or unverified internal task blocks every later item. The next user message becomes recovery guidance and ForceFlow retries the blocked item automatically instead of silently advancing.
- Autonomous recovery continues to honor existing approval and Smart Autopilot safety floors; exhausted repair budgets fail closed instead of looping indefinitely.

## [7.6.5] - 2026-08-01

### Added

- Added `/watchdog off` (also `unlimited`) for slow APIs. It removes first-response, streaming-idle, total-call, socket-read, retry-budget, helper-call, and subagent request time limits.

### Changed

- Unbounded API calls still run in detachable background workers, retain five-second progress heartbeats, accept live prompt input, and remain immediately cancellable with Ctrl+C.
- Selecting `fast`, `balanced`, or `patient` automatically re-enables the request watchdog.

## [7.6.4] - 2026-08-01

### Fixed

- Explicit custom routes ending in `/chat/completions` now permanently select OpenAI Chat wire format, while `/messages` routes select Anthropic Messages format regardless of the first discovered model name.
- Migrated older custom connections that learned Anthropic plus `x-api-key` from a Claude-first model list even though the user entered a Chat Completions URL. Authentication is safely re-detected with the corrected protocol.
- Prevented `/protocol` from creating a route/payload mismatch when an explicit endpoint already determines the protocol.

## [7.6.3] - 2026-08-01

### Added

- Added FreeModel as a first-class provider using its documented `https://api.freemodel.dev/v1` OpenAI-compatible API, `auto` model router, Bearer authentication, and `FREEMODEL_API_KEY` environment variable.
- Existing keys saved against a FreeModel custom host are reused locally when switching to the new provider, without exposing or duplicating the secret outside ForgeCode settings.

### Fixed

- Successful HTTP responses containing neither visible text nor tool calls are now rejected as malformed completions instead of being reported as a ready connection or a completed task.

## [7.6.2] - 2026-08-01

### Fixed

- Preserved visible streamed output when an OpenAI-compatible gateway returns a minimal completion envelope without final output content.
- Added one bounded final-response recovery turn when a model finishes tool work without producing a user-visible result.
- Removed the contradictory `Tamamlandı` plus `model produced no final result` combination. ForceCode now verifies the exact answer shown to the user and does not claim completion if the model remains empty.

## [7.6.1] - 2026-07-22

### Added

- Added a dependency-free native Windows ForceSandbox engine built on AppContainer process isolation. Each project receives a distinct security identity and execution directory under `C:\ForceCodeSandbox`.
- Added native process-tree containment, active-process and memory limits, sanitized environments, private home/temp directories, optional outbound internet capability, and interactive stdin/stdout support.
- Added a shared minimal Python 3 runtime for isolated project tests. It excludes host `site-packages`, user packages, credentials, and API keys.

### Changed

- Windows `sandbox_engine=auto` now selects the native engine without probing or requiring Docker. Docker and Podman remain optional explicit engines and the non-Windows fallback.
- Network mode changes now recreate the native runner with a separate online or offline AppContainer profile.
- `/sandbox` can cycle through `auto`, `native`, `docker`, and `podman`.

### Fixed

- Fixed startup crashes when OneDrive or Windows exposes an unreadable path such as `...`; inaccessible entries are skipped instead of aborting project staging.
- Removed recursive ACL changes to the host Python installation, eliminating long startup stalls and preventing ForceSandbox from broadening access to user-installed packages.
- Filtered a harmless CPython AppContainer real-path diagnostic from command and interactive-process output.

### Security

- Verified locally that online sandboxes retain outbound HTTPS, offline sandboxes block it, project identities cannot read one another, host user files remain inaccessible, and project files plus scripted stdin still work.

## [7.6.0] - 2026-07-22

### Added

- Added default-on ForceSandbox workspaces under ForgeCode's AppData directory. AI file tools now operate on a private, secret-filtered project copy rather than the real project.
- Added Docker/Podman command isolation with a project-only mount, ephemeral read-only container filesystem, optional network blocking, dropped Linux capabilities, and no inherited API keys or host environment.
- Added verified transfer gates, concurrent-edit conflict detection, per-task path scoping, pre-transfer snapshots, integrity checks, rollback, pending-change retention, and redacted security logs.
- Added an arrow-key `/sandbox` control menu for status, network, automatic transfer, snapshots, pending transfer, workspace, logs, engine selection, restore, and cleanup.

### Changed

- ForceGraph continues to work against the private sandbox copy so structural analysis does not expose the real project workspace to model tools.
- Automatic project tests use container-native commands and can pass scripted or interactive input through the isolated runtime.

### Security

- Generic command execution now fails closed when Docker or Podman is unavailable instead of silently falling back to the host shell.
- Common environment files, credentials, private keys, SSH/cloud configuration directories, symlinks, and Windows reparse points are excluded or rejected at the sandbox boundary.
- A successful task transfers only files changed during that task; older unverified sandbox work cannot piggyback on a later successful verification.

## [7.5.0] - 2026-07-22

### Added

- Added a request lifecycle watchdog with independent first-response, streaming-idle, and total-call budgets. Active SSE traffic refreshes the idle window, while stalled calls are detached before they can block the terminal for several minutes.
- Added `/watchdog fast|balanced|patient|status`, compact stall receipts in `/diagnostics`, and watchdog details in `/status`.
- Added a shared cancellation signal for detached API workers so late failures cannot trigger another transport retry after the user or watchdog has already moved on.
- Added a total retry-time budget. Retry count, delay, and cumulative time can now be controlled together with `/retry <count> [delay] [budget]`.

### Changed

- Streaming sockets now use an inactivity timeout instead of being unbounded. Long, actively producing responses still continue normally.
- Planner, safety-classifier, and other helper calls use a short bounded wait so an optional preflight cannot hold up the main task.
- Provider latency now recognizes the first received SSE activity even when a tool call streams without visible text.

### Fixed

- Prevented the previous 100-second transport timeout multiplied by retries and recovery calls from turning one failed request into a 200-300 second wait.
- Plain-JSON fallback after unsupported SSE is bounded and cancellation-aware instead of waiting indefinitely.

## [7.4.5] - 2026-07-22

### Added

- Added `/route off` for custom providers. It sends chat or Anthropic requests directly to the configured base URL without appending `/chat/completions`, `/v1/messages`, or another standard route.
- Root-only custom connections now select the clearer `off` route automatically; the existing `exact` value remains fully backward compatible.

## [7.4.4] - 2026-07-22

### Fixed

- Custom API health checks now treat generic API 305/unavailable and 429/rate-limit responses as service-wide terminal probe results instead of testing every discovered model.
- `/connect` preserves the entered key, selected model, route, and first protocol when a service is temporarily unavailable, and skips the second protocol to avoid doubling rate-limit pressure.
- Genuine model errors that explicitly advertise supported models still receive bounded recovery, now capped at three alternatives per health check.

## [7.4.3] - 2026-07-22

### Changed

- Raised the native ForceGraph compatibility floor to 2.7.0 and updated active documentation for Task Passports, the five-tool compact MCP profile, and soft token-budget optimization.
- Existing ForceGraph 2.6 installations now upgrade automatically before eligible graph-backed work.

### Fixed

- A recent installation failure recorded for an older compatibility floor no longer blocks a newly required ForceGraph upgrade for one hour.
- Automatic upgrade and externally updated package versions now refresh the local ForceGraph receipt even when project source files did not change.
- `/graph` now prefers the live installed package version over stale receipt data and marks versions below the required compatibility floor.

## [7.4.2] - 2026-07-21

### Changed

- Updated the native ForceGraph compatibility floor from 2.4.0 to 2.6.0; the current upstream repository reports 2.6.1.
- Existing 2.4/2.5 installations are now upgraded automatically before eligible graph-backed coding work.
- Updated documentation to distinguish ForgeCode's native CLI bridge from ForceGraph 2.6's optional compact MCP gateway and shared-agent memory.

## [7.4.1] - 2026-07-21

### Fixed

- Short greetings and language preferences now use a lightweight chat plan with no project tools, graph scan, evidence template, or unnecessary token overhead.
- Turkish UI sessions now explicitly keep the complete model response in Turkish unless the user requests another language.
- An empty ForceGraph database created by status migrations is no longer mistaken for a successfully built project graph.
- `/graph` now reports empty/non-code folders clearly and filters migration log noise from status output.
- `/graph on` and `/graph off` now work as direct aliases for `/graph auto on|off`.

## [7.4.0] - 2026-07-21

### Changed

- Upgraded the native integration contract to ForceGraph 2.4.0 and its universal, always-current workflow.
- ForceGraph now installs or upgrades itself on the first eligible coding request, builds the initial project graph, and incrementally synchronizes changed source files before later graph analysis.
- Manual installation, build, and update commands are no longer required for normal use; they remain available for diagnostics and recovery.

### Added

- Local `.forgecode/forcegraph-state.json` and `.code-review-graph/forgecode-auto-receipt.json` receipts with version, source signature, action, status, and errors.
- `/graph auto on|off` for explicit user control and `/graph repair` for forced recovery.
- Automatic ForceGraph status in `/doctor` and `/dashboard`.

### Reliability and privacy

- Automatic graph failures degrade gracefully without blocking the AI request, and repeated installation failures use a one-hour retry cooldown.
- ForceCode uses request-time native synchronization instead of modifying other AI clients' MCP settings or leaving a watcher process running.
- ForceGraph runs only for projects containing supported source files; local graph and automation directories remain excluded from AI context and Git.

## [7.3.0] - 2026-07-21

### Added

- Optional native integration with [ForceGraph](https://github.com/samansarmasik-alt/code-review-graph), while keeping the core ForgeCode runtime dependency-free.
- `/graph status|install|build|update|open`, `/impact [base]`, and `/review [base]` commands.
- A read-only `graph_context` model tool for structural impact, test-gap, and review evidence in main, plan, and subagent modes.
- ForceGraph consultation metadata in Execution Kernel run receipts.

### Security and performance

- ForceGraph subprocesses use argument arrays with `shell=False`, project-scoped working directories, bounded timeouts, UTF-8-safe output, and validated Git base references.
- `.code-review-graph` databases are excluded from ForgeCode/ForceContext scans and Git by default.

## [7.2.1] - 2026-07-19

### Fixed

- Multi-line clipboard content pasted at `you ›` is now collected and sent as one prompt instead of treating later lines as live intervention messages.
- Multi-line text pasted while a request is active becomes one queued prompt or one steering message, preserving its line breaks.
- Windows `CRLF`, `CR`, and `LF` clipboard line endings are normalized consistently without flattening the request.

## [7.2.0] - 2026-07-18

### Added

- Project-aware `test_project` verification with automatic detection for Python, Node.js, Go, Rust, .NET, Maven, Gradle, and static HTML projects.
- Persistent interactive process tools that let the model see prompts, provide staged input, inspect output, and stop programs without taking over ForgeCode's own input line.
- Live program and command progress in the terminal activity area, including prompts that do not end with a newline.
- Static web auditing for missing local assets, duplicate element IDs, missing image alternatives, and incomplete form controls.

### Fixed

- Close stdin for ordinary commands by default so programs that wait for input fail clearly instead of hanging the agent.
- Preserve scripted stdin and UTF-8 output safely across Windows command execution.
- Require relevant post-change verification before the Execution Kernel accepts successful artifact completion.
- Keep safe read-only commands on the internal file reader when command metadata includes stdin state.

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
