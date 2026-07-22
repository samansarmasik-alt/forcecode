# ForgeCode

Current release: **v7.6.0**. ForceSandbox runs AI work in a private project copy, executes shell commands through Docker or Podman, and transfers only verified, conflict-free changes back to the real project.

ForgeCode is a lightweight, dependency-free terminal coding agent for Windows. It connects to multiple AI providers, works inside the directory from which it is launched, and gives the model a controlled set of file, search, command, diagnostics, and delegation tools.

The terminal interface supports both English and Turkish. New installations ask for a language before provider setup; existing users can switch at any time with `/language en` or `/language tr`.

> [!IMPORTANT]
> ForgeCode is an independent open-source project. It is not affiliated with, endorsed by, or distributed by OpenAI, Anthropic, or any supported provider.

## Highlights

- One Python file and no third-party runtime dependencies.
- Anthropic Messages, OpenAI Responses, and OpenAI-compatible Chat Completions transports.
- More than twenty provider presets, local Ollama/LM Studio support, and configurable custom endpoints.
- Model discovery, connection tests, response-latency history, token accounting, and configurable pricing.
- Project-scoped file inspection, verified UTF-8 writes, text replacement, search, and command execution.
- Default-on ForceSandbox isolation with project-only container mounts, snapshots, conflict detection, rollback, and controlled transfer.
- Streaming output, prompt queueing, persistent sessions, project memory, goals, and optional backup API failover.
- Multi-line clipboard prompts are submitted as one request, including while using the live queue or steering input.
- ForceContext context receipts, token-budgeted memory retrieval, incremental project indexing, and verified response learning.
- Optional ForceGraph structural code intelligence for impact analysis, test-gap discovery, and graph-assisted review.
- Evidence-oriented Execution Kernel with local planning, structured debugging, verification gates, and confidence receipts.
- AI-selected read-only subagents for research, design, backend, frontend, testing, review, and security tasks.
- Project-aware verification and interactive program testing: ForceCode can follow terminal prompts, provide staged input, and show live process output in the activity area.
- Explicit approval controls plus Smart Autopilot risk assessment for project mutations.

## Safety model

ForceSandbox is enabled by default. AI file tools see only a private copy under the ForgeCode AppData directory, while generic shell commands run in an ephemeral Docker/Podman container that mounts only that copy. If no working isolation engine is available, shell commands fail closed; file tools remain available in the private workspace. Secrets and common credential files are excluded from staging.

Verified, conflict-free task changes are atomically transferred to the real project after a snapshot. Failed verification or a concurrently changed real file keeps the work inside the sandbox. Empty paths, directory targets, traversal, links, and reparse points are rejected. Trusted ForceCode controllers handle snapshots, provider requests, and the argument-constrained ForceGraph bridge; ForceGraph analyzes the sandbox copy rather than the real project.

Commands and file changes require confirmation by default. Smart Autopilot can approve clearly safe project work, while a deterministic safety layer blocks known destructive system operations. Full autopilot is available but should be enabled only in a disposable or version-controlled workspace.

API keys can be stored by the application, but environment variables are preferable for sensitive or shared machines. Never commit API keys, `.forgecode` project state, logs, or local configuration.

See [SECURITY.md](SECURITY.md) for reporting vulnerabilities and the supported-version policy.

## Requirements

- Windows 10 or later
- Python 3.10 or later, available as `py -3` or `python`
- Docker Desktop or Podman for isolated AI shell commands; without one, command tools are safely blocked
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
| Request reliability | `/watchdog fast\|balanced\|patient`, `/retry <count> [delay] [budget]` |
| Safety | `/autopilot smart\|on\|off`, `/doctor`, `/diagnostics`, `/logs` |
| Sandbox | `/sandbox` (arrow-key settings, pending transfer, snapshots, logs, cleanup) |
| Continuity | `/goal`, `/resume`, `/sessions`, `/session`, `/memory`, `/remember`, `/init` |
| ForceContext | `/force-context-init`, `/force-context-scan`, `/force-context-update`, `/force-memory-stats` |
| ForceGraph | `/graph`, `/impact`, `/review` |
| Execution engine | `/plan`, `/debug`, `/confidence`, `/engine` |
| Parallel work | `/agents`, `/agent`, `/delegate`, `/team`, `/batch` |
| Usage | `/status`, `/usage`, `/history`, `/context`, `/activity`, `/dashboard` |
| Help | `/help`, `/clear`, `/exit` |

Run `/help` for the complete command list and usage syntax.

## ForceSandbox

No per-task sandbox command is required. Each request works in a ForceCode-owned copy, keeps internet access enabled by default, and exposes no host Desktop, Documents, other projects, saved API keys, or system folders to model tools. Open `/sandbox` to view status and the workspace, toggle network or automatic transfer, create/restore snapshots, inspect redacted logs, select Docker/Podman, or clean the isolated copy. Set `sandbox_enabled` to `false` only if you intentionally want the legacy direct-workspace behavior; restart ForceCode after changing it.

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
