# ForgeCode

Current development version: **v7.11.1**. It adds adaptive stuck-connection recovery while preserving unlimited active generation with `/watchdog off`. Skill Scout, VibeCode checkpointed autonomy, the language-independent project toolchain, pinned-model default, and ForceSandbox isolation remain intact.

ForgeCode is a lightweight, dependency-free terminal coding agent for Windows. It connects to multiple AI providers, works inside the directory from which it is launched, and gives the model a controlled set of file, search, command, diagnostics, and delegation tools.

The terminal interface supports both English and Turkish. New installations ask for a language before provider setup; existing users can switch at any time with `/language en` or `/language tr`.

> [!IMPORTANT]
> ForgeCode is an independent open-source project. It is not affiliated with, endorsed by, or distributed by OpenAI, Anthropic, or any supported provider.

## Highlights

- One Python file and no third-party runtime dependencies.
- Anthropic Messages, OpenAI Responses, and OpenAI-compatible Chat Completions transports.
- More than twenty provider presets, local Ollama/LM Studio support, and configurable custom endpoints.
- First-class FreeModel support through `https://api.freemodel.dev/v1` with the `auto` router and standard Bearer authentication.
- Model discovery, connection tests, response-latency history, token accounting, and configurable pricing.
- Project-scoped file inspection, verified UTF-8 writes, text replacement, search, and command execution.
- Transactional multi-file exact edits plus compact SHA-256/UTF-8 artifact verification tools.
- Default-on ForceSandbox isolation with a native Windows AppContainer engine, per-project identities, snapshots, conflict detection, rollback, and controlled transfer.
- Streaming output, prompt queueing, persistent sessions, project memory, goals, and optional backup API failover.
- Automatic ForceFlow AI task decomposition, crash-safe sequential execution, evidence-guided unattended repair, and verification-gated progression without manual queue commands.
- VibeCode overnight product mode with architecture-first planning, per-task checkpoints, context compaction, long build budgets, API backoff, crash resume, repair cycles, and an independent read-only final reviewer.
- Low-latency coordination: ordinary builds skip the remote planning/orchestration fan-out, optional preflights are bounded, and `/watchdog off` keeps active main-model generations unlimited while safely recovering connections that stop producing data.
- A model-independent web quality gate that rejects broken assets, placeholders, weak one-file scaffolds, missing responsive behavior, and basic accessibility failures before a site can be reported complete.
- Multi-line clipboard prompts are submitted as one request, including while using the live queue or steering input.
- ForceContext context receipts, token-budgeted memory retrieval, incremental project indexing, and verified response learning.
- Optional ForceGraph structural code intelligence for impact analysis, test-gap discovery, and graph-assisted review.
- Evidence-oriented Execution Kernel with local planning, structured debugging, verification gates, and confidence receipts.
- AI-selected read-only subagents for research, design, backend, frontend, testing, review, and security tasks.
- Project-aware verification and interactive program testing: ForceCode can follow terminal prompts, provide staged input, and show live process output in the activity area.
- A general project toolchain that detects CMake, .NET, Maven, Gradle, Cargo, Go, Node, and Python projects; creates verified multi-file C++ executables, .NET apps, Java JARs, and Minecraft Paper plugins; and refuses to report a binary build without artifact evidence.
- Explicit approval controls plus Smart Autopilot risk assessment for project mutations.

## Safety model

ForceSandbox is enabled by default. AI file tools see only a private copy under the ForgeCode AppData directory. On Windows, generic commands run with a unique AppContainer identity in `C:\ForceCodeSandbox`; kernel ACLs block Desktop, Documents, other projects, saved keys, and other user data. Internet is enabled by default and can be disabled with `/sandbox`. Required Windows binaries and a minimal, key-free Python standard-library runtime are read-only. Docker and Podman remain optional engines for non-Windows systems or explicit selection. If no working isolation engine is available, shell commands fail closed; file tools remain available in the private workspace.

Verified, conflict-free task changes are atomically transferred to the real project after a snapshot. Failed verification or a concurrently changed real file keeps the work inside the sandbox. Empty paths, directory targets, traversal, links, and reparse points are rejected. Trusted ForceCode controllers handle snapshots, provider requests, and the argument-constrained ForceGraph bridge; ForceGraph analyzes the sandbox copy rather than the real project.

Commands and file changes require confirmation by default. Smart Autopilot can approve clearly safe project work, while a deterministic safety layer blocks known destructive system operations. Full autopilot is available but should be enabled only in a disposable or version-controlled workspace.

API keys can be stored by the application, but environment variables are preferable for sensitive or shared machines. Never commit API keys, `.forgecode` project state, logs, or local configuration.

See [SECURITY.md](SECURITY.md) for reporting vulnerabilities and the supported-version policy.

## Requirements

- Windows 10 or later
- Python 3.10 or later, available as `py -3` or `python`
- Windows 10/11: no Docker dependency; ForceSandbox uses the built-in AppContainer security boundary
- Linux/macOS: Docker or Podman for isolated AI shell commands; without one, command tools are safely blocked
- An API key for the selected hosted provider; Ollama and LM Studio can run locally without one

## Quick start

Clone or download the repository, open PowerShell in the repository, and run:

```powershell
.\forgecode.bat .
```

On first launch, select a provider, enter its key with `/key`, and verify the connection with `/test`.

To install the global `Force` command, run:

```powershell
.\install-force.ps1
```

Open a new terminal and launch ForgeCode from any project directory:

```powershell
cd C:\path\to\your-project
Force
```

The installer copies the runtime files to `%LOCALAPPDATA%\ForgeCode\app` and adds `%LOCALAPPDATA%\ForgeCode\bin` to the user `PATH`. The checkout can then be moved or removed without breaking the installed command. Re-run the installer after upgrading ForgeCode.

To uninstall the global command while preserving user settings:

```powershell
.\uninstall-force.ps1
```

## Usage

Type a request directly:

```text
you › inspect this project, fix the failing tests, and explain the changes
```

ForgeCode asks before file or command operations unless an autopilot mode is enabled. While a model is working, a normal message followed by Enter steers the active request. `/queue <message>` adds work without interrupting it, and Ctrl+C stops the current request while retaining a short progress summary for the next prompt.

Streaming is enabled by default for every model and tool-follow-up round, including subagents and one-shot use. If a provider truncates a file-tool JSON payload, ForgeCode rejects the incomplete call, preserves a valid provider transcript, raises the next retry to the configured output budget, and verifies that successful write receipts correspond to real project files.

One-shot mode is also available after initial setup:

```powershell
Force -p "Review the current changes and run the relevant tests"
```

### Common commands

| Area | Commands |
| --- | --- |
| Setup | `/providers`, `/provider`, `/key`, `/test`, `/models`, `/model` |
| Language | `/language en`, `/language tr` |
| Custom APIs | `/connect`, `/protocol`, `/route`, `/endpoint`, `/profiles`, `/profile` |
| Work modes | `/mode`, `/thinking`, `/temperature`, `/efficiency`, `/power`, `/stream` |
| Request reliability | `/watchdog off\|fast\|balanced\|patient`, `/retry <count> [delay] [budget]` |
| Safety | `/autopilot smart\|on\|off`, `/doctor`, `/diagnostics`, `/logs` |
| Sandbox | `/sandbox` (arrow-key settings, pending transfer, snapshots, logs, cleanup) |
| Skills | `/skills`, `/skill scout status\|scan\|on\|off`, `/skill show\|install\|update\|enable\|disable\|remove` |
| Continuity | `/goal`, `/resume`, `/sessions`, `/session`, `/memory`, `/remember`, `/init` |
| ForceContext | `/force-context-init`, `/force-context-scan`, `/force-context-update`, `/force-memory-stats` |
| ForceGraph | `/graph`, `/impact`, `/review` |
| Execution engine | `/plan`, `/debug`, `/confidence`, `/engine` |
| Sequential work | Automatic ForceFlow on normal project requests; no command required |
| Overnight autonomy | `/vibe <goal>`, `/vibe on`, `/vibe status`, `/vibe resume`, `/vibe stop`, `/vibe hours <1-24>` |
| Parallel work | `/agents`, `/agent`, `/delegate`, `/team` |
| Usage | `/status`, `/usage`, `/history`, `/context`, `/activity`, `/dashboard` |
| Help | `/help`, `/clear`, `/exit` |

Run `/help` for the complete command list and usage syntax.

### Slow API and stall recovery

`/watchdog off` removes the total main-model generation deadline; it does not leave a silent dead connection alive forever. By default, ForceCode detaches a connection after 120 seconds without first data or 180 seconds without streaming progress, then safely retries once against the same pinned model if no visible answer was emitted. Healthy slow-provider latency history automatically raises these limits. Active streams may run indefinitely.

For unusually slow services, adjust the independent limits without restoring a total timeout:

```text
/set stall_first_response_seconds 300
/set stall_stream_idle_seconds 600
/set stall_retry_attempts 2
```

Set `stall_retry_attempts` to `0` to keep detection but disable automatic retry. The protection itself can be explicitly disabled with `/set stall_guard_enabled false`, though this permits genuinely dead connections to wait until Ctrl+C.

## Agent Skills

ForgeCode supports the portable `SKILL.md` directory format with YAML frontmatter (`name`, `description`, and optional `version`/`triggers`). Skill metadata stays local, and only the instructions selected for the current task are added to model context. This progressive-disclosure design avoids sending every installed skill on every request.

Nine dependency-free skills are built in and enabled by default: `skill-scout`, `debug-root-cause`, `frontend-quality`, `project-audit`, `release-readiness`, `native-cpp`, `dotnet-application`, `java-jar`, and `minecraft-paper-plugin`. List or inspect them with:

```text
/skills
/skill scout status
/skill scout scan
/skill show frontend-quality
/skill discover vercel-labs/agent-skills
```

### Automatic skills.sh Skill Scout

Skill Scout analyzes the current repository and active task locally, then sends only generic labels such as `python`, `react`, `testing`, or `frontend-design` to the public skills.sh catalog search. Source code, file paths, prompts, API keys, and user data are never sent. It downloads only candidates that match the detected project, combines independent skills.sh audit-provider verdicts with a deterministic local scan for prompt injection, credential access, sandbox bypass, destructive commands, host-level changes, and unsupported companion files, and assigns security and project-contribution scores.

Automatic installation requires a security score strictly above 80/100 and a contribution score of at least 60/100. Critical findings always block installation regardless of score. At most two skills are added per scan and eight automatic skills per project by default. Accepted skills are written only to `.forgecode/skills`; scripts, binaries, hooks, assets, references, and dependencies are never imported or executed. The decision receipt is stored locally in `.forgecode/skill-scout.json`. Use `/skill scout off` to disable discovery, `/skill scout on` to re-enable it, or adjust the typed `skill_scout_*` settings with `/set`.

Install a skill for all projects or only the current project from an HTTPS GitHub repository, `tree`/`blob` URL, raw `SKILL.md` URL, or `owner/repo` shorthand:

```text
/skill install owner/repo user
/skill install owner/repo@skill-name user
/skill install https://github.com/owner/repo/tree/main/skills/frontend project
/skill update frontend
/skill disable frontend
/skill remove frontend
```

Natural-language requests such as “install this GitHub skill” expose the existing manual operations to the selected AI. Remote manual changes are rejected unless the current user request explicitly asks for skill management. GitHub imports are limited to a UTF-8 `SKILL.md` file (128 KB maximum); scripts, binaries, hooks, and executable dependencies are never imported or run automatically. Public repositories work without setup; private repository discovery can use a user-supplied `GITHUB_TOKEN` environment variable, which ForgeCode never stores in skill metadata. User skills live in `%LOCALAPPDATA%\ForgeCode\skills`; project skills live in `.forgecode\skills`. Project skills override user skills, which override built-ins with the same name. Set `skill_auto_select` to `false` to keep skills installed but require explicit `$skill-name` selection, or set `skills_enabled` to `false` to disable the engine.

## General project toolchain

The model receives one guarded `project_toolchain` tool instead of HTML-only assumptions. It can inspect an existing repository, select its native build system, and run `build`, `test`, or `package` through the same approvals, ForceSandbox isolation, timeout controls, activity logs, and UTF-8 handling as other ForceCode tools. New-project scaffolding supports:

- `cpp-cmake`: modern CMake library/executable separation plus CTest.
- `dotnet-exe`: nullable C# console app and platform-specific single-file publish.
- `java-jar`: standard Maven layout with an executable JAR manifest.
- `paper-plugin`: Gradle Kotlin DSL, Paper API, `JavaPlugin`, commands, and `plugin.yml`.

Existing Maven/Gradle wrappers are preferred automatically. CMake, .NET, Java/Paper, Rust, and packaged Go work is not marked successful unless a non-empty executable or JAR artifact is found after the command. The AI chooses and uses this tool from ordinary requests such as “build a C++ app”, “package this as an EXE”, or “create a Paper plugin”; no extra slash command is required.

The selected model remains pinned when a provider reports it as unavailable. To explicitly allow ForceCode to probe and permanently select another model from the same custom/Kimchi service, enable the optional setting:

```text
/set auto_model_switch true
```

Disable it again with `/set auto_model_switch false`.

## ForceFlow sequential tasks

ForceFlow is for work that must happen in order. Write the request normally. Cohesive requests such as creating one website or fixing one bug become one local task instantly. Only explicit sequences, multi-domain objectives, structured lists, and very large requests call the selected model for decomposition. ForceCode stores the resulting plan locally and executes one item at a time. Every task receives its own acceptance criterion and Execution Kernel receipt. Later tasks stay blocked until the current task has a visible final result, verified project artifacts, and any required focused test evidence.

ForceFlow itself is already an orchestrator, so it does not launch another remote orchestration preflight for every subtask. The main model still has the `delegate_task` tool and may start a focused specialist when useful. Planner/orchestrator/safety preflights use `preflight_timeout_seconds` (12 seconds by default); `/watchdog off` continues to apply to the main generation, not optional helpers.

```text
you › add authentication, then build the settings UI, then test the complete flow

ForceFlow › AI created 3 ordered tasks
ForceFlow › task 1 verified → task 2 started
ForceFlow › task 2 verified → task 3 started
forge › all tasks completed and verified
```

Each subtask keeps the original user objective, so quality requirements are not lost when a large request is divided. If normal attempts fail, ForceFlow enters bounded autonomous repair rounds: it carries forward missing evidence and API/tool diagnostics, asks for a different root-cause-driven approach, reruns focused checks, and continues without waiting for another prompt. It still stops safely when repair evidence never passes or an existing approval policy requires user confirmation.

Framework-free website work receives a final deterministic quality gate independent of the selected model. Serious static sites must have linked HTML, responsive CSS, and functional JavaScript, plus semantic structure, mobile metadata, valid local assets, accessible basics, and non-placeholder content. React, Next, Vue, Svelte, and similar projects keep their framework and use its native test/build gate instead. A failed gate creates its own internal repair task and is rechecked before completion. Ctrl+C marks the running item as paused; the next normal prompt resumes it with fresh guidance. State is stored in `.forgecode/tasks.json` and is excluded from Git. See [docs/FORCEFLOW.md](docs/FORCEFLOW.md) for the state model and verification rules.

## VibeCode overnight autonomy

VibeCode turns one broad product goal into a supervised-by-evidence overnight run. Start it directly, or arm the next normal prompt:

```text
/vibe hours 10
/vibe Build a polished desktop-ready application from this project, test every important flow, and leave it ready to release
```

The planner creates an ordered architecture and acceptance plan. ForceCode then completes one task at a time, saves a checkpoint, and clears expensive conversation context before continuing. Long compilers and test suites receive a separate command budget; temporary API failures use capped exponential backoff. A repeatedly blocked local task can be deferred so unrelated work continues, but the final result cannot pass while the independent reviewer still considers that gap important.

VibeCode never silently weakens the safety boundary. It requires ForceSandbox, auto-approves only isolated project work, blocks known destructive commands, and transfers verified changes through the existing snapshot/conflict controls. A crash or Ctrl+C leaves `.forgecode/vibe-session.json` resumable with `/vibe resume`. The latest objective, task receipts, checks, changed files, and outcome are written to `.forgecode/vibe-report.md`. Use `/vibe status` at any time; `/vibe stop` abandons the saved run without deleting project changes.

## ForceSandbox

No per-task sandbox command is required. Each request works in a ForceCode-owned copy and keeps internet access enabled by default. Windows commands run in a native AppContainer process tree with a separate identity per project, a private home/temp area, a process and memory limit, sanitized environment variables, and no inherited API key. A compact shared Python runtime contains the standard library but excludes host `site-packages` and user packages. The aggregate project and verified-transfer size is unlimited by default (`sandbox_max_transfer_mb: 0`); set a positive MB value only when you intentionally want a cap. The separate per-file guard remains configurable with `sandbox_max_file_mb`. Open `/sandbox` to view status and the workspace, toggle network or automatic transfer, create/restore snapshots, inspect redacted logs, select `auto`, `native`, Docker, or Podman, or clean the isolated copy. Set `sandbox_enabled` to `false` only if you intentionally want the legacy direct-workspace behavior; restart ForceCode after changing it.

## Execution Kernel

ForgeCode 7 separates planning, debugging, verification, confidence, and token allocation instead of asking one model loop to handle every concern implicitly. A short local execution contract defines evidence requirements without spending an additional API request. Tool failures receive stable categories and recovery guidance, while deterministic verification gates prevent prose-only completion claims.

```text
/plan fix the API timeout
/debug
/confidence
/engine
```

The latest compact run receipt is stored in `.forgecode/last-run.json`. It contains the public plan, tool-derived evidence, error categories, missing verification, and confidence components—never private chain-of-thought. See [docs/EXECUTION_ENGINE.md](docs/EXECUTION_ENGINE.md) for the design rationale and trust model.

## ForceContext

ForceContext is opt-in. It keeps user preferences, verified project facts, and expiring session notes in separate layers. Before each request, its Context Engine identifies intent, retrieves relevant cards, redacts secrets, applies a strict token budget, and sends only the compiled subset. A Context Receipt records what was selected, why, and its estimated token cost.

Initialize and scan from inside ForgeCode:

```text
/force-context-init
/force-context-scan
/force-context-update project api-rule Use typed API errors
/context preview fix the API error handler
/force-memory-stats
```

The same four `force-context-*` commands work directly after `Force`, for example `Force force-context-scan`. Use `/memory list`, `/memory edit`, `/memory delete`, `/memory disable`, `/memory export`, or `/memory wipe` for complete user control. The Response Analyzer stores possible decisions as low-confidence suggestions; only outcomes backed by changed files and reported verification become verified memory.

ForceContext data is local, but selected memory snippets are included in requests to your configured provider. `.forceignore` excludes paths from scanning. `.force/` and memory exports must not be committed.

## Automatic ForceGraph integration

[ForceGraph 2.7+](https://github.com/samansarmasik-alt/code-review-graph) is an optional local-first structural code graph, integrated as an automatic ForceCode subsystem. ForgeCode requires the 2.7 compatibility line (the upstream repository currently reports 2.7.0). There is no required setup command: on the first request in a project containing supported source files, ForgeCode installs or upgrades an older ForceGraph version, builds the graph, verifies the local database, and records an automation receipt. Later requests compare a compact source snapshot and incrementally index only changed files before graph-backed analysis.

The AI can call the read-only `graph_context` tool before broad file scans. This provides focused architecture, blast-radius, test-gap, and review evidence while the Execution Kernel records whether graph evidence was consulted. Failure is non-fatal: ForgeCode reports a concise activity message, applies a one-hour retry cooldown, and continues with its normal file tools.

Manual commands remain only for visibility and recovery:

```text
/graph                 # automatic state and native graph status
/graph auto off        # opt out without deleting local data
/graph repair          # force installation/build/update recovery
/impact HEAD~1         # compact blast-radius and test-gap report
/review main           # detailed graph-assisted review
/graph open            # optional visual graph
```

ForgeCode's native bridge does not rewrite Codex, Claude Code, Cursor, or other clients' MCP configuration. It uses the ForceGraph 2.7 CLI directly and provides request-time automatic synchronization, so no persistent watcher process or editor restart is required. ForceGraph's separate `connect` workflow exposes a five-tool compact MCP gateway, shared-agent memory, Task Passports, and soft token-budget optimization to supported external clients. Those MCP-only features are not silently enabled or falsely reported as native ForgeCode features. Graph databases stay in `<project>/.code-review-graph`, automation state stays in `<project>/.forgecode/forcegraph-state.json`, and both are excluded from normal context scans and Git. Source code is not uploaded by the native bridge.

## Provider configuration

ForgeCode includes presets for Anthropic, OpenAI, OpenRouter, Gemini, Groq, Mistral, DeepSeek, xAI, Together, Fireworks, Perplexity, Cerebras, SambaNova, NVIDIA NIM, Cohere, Kimchi, GitHub Models, Hugging Face, SiliconFlow, DashScope, Ollama, and LM Studio.

For a custom OpenAI-compatible or Anthropic-compatible endpoint:

```text
/provider custom
/connect https://your-service.example
/route off                  # send directly to the configured base URL
/protocol auto
/key
/models
/test
```

Use only services you are authorized to access. ForgeCode does not attempt to bypass provider client restrictions, access controls, or terms of service.

The optional backup connection can continue after a supported quota or rate-limit failure:

```text
/backup set <provider-or-saved-profile> [model]
/backup key
/backup test
/backup on
```

## Data locations

Global user settings remain outside the repository:

| Data | Default location |
| --- | --- |
| Configuration and saved keys | `%LOCALAPPDATA%\ForgeCode\config.json` |
| Usage history | `%LOCALAPPDATA%\ForgeCode\usage.jsonl` |
| Crash log | `%LOCALAPPDATA%\ForgeCode\crash.log` |
| Installed runtime | `%LOCALAPPDATA%\ForgeCode\app` |
| Global launcher | `%LOCALAPPDATA%\ForgeCode\bin\Force.cmd` |
| User-level ForceContext preferences | `%LOCALAPPDATA%\ForgeCode\memory\user.json` |
| ForceSandbox workspaces, snapshots, and logs | `%LOCALAPPDATA%\ForgeCode\sandboxes\<project-id>` |
| User-wide Agent Skills and enable/disable state | `%LOCALAPPDATA%\ForgeCode\skills` |

`FORGECODE_HOME` can override the global settings directory. On first launch after upgrading, legacy Windows settings from `%USERPROFILE%\.forgecode` are copied to AppData when no AppData configuration exists; the legacy files are not deleted automatically.

Project-specific operational state stays in `<project>\.forgecode`. ForceContext project/session cards, its incremental index, and Context Receipts stay in `<project>\.force`. Both directories are ignored by Git.

Optional ForceGraph indexes stay in `<project>\.code-review-graph` and are also ignored by Git.

## Development

ForgeCode intentionally has no runtime package dependencies. Run the complete test suite with:

```powershell
python -m unittest discover -s tests -v
```

Check syntax and the CLI entry point with:

```powershell
python -m py_compile forgecode.py
python forgecode.py --version
```

Repository layout:

```text
.
├── .github/                 Issue and pull-request templates
├── tests/                   Unit and integration-style tests
├── forgecode.py             Application and CLI entry point
├── forgecode.bat            Portable Windows launcher
├── install-force.ps1        Per-user global command installer
├── uninstall-force.ps1      Global command uninstaller
├── config.example.json      Sanitized configuration reference
├── pyproject.toml           Python project metadata
├── CONTRIBUTING.md          Contribution workflow
├── SECURITY.md              Security policy
├── CHANGELOG.md             Release notes
└── LICENSE                  MIT License
```

Before opening a pull request, read [CONTRIBUTING.md](CONTRIBUTING.md), add or update tests for behavior changes, and keep provider credentials out of fixtures and logs.

## License

ForgeCode is released under the [MIT License](LICENSE).
