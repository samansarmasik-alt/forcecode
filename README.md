# ForgeCode

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
- Streaming output, prompt queueing, persistent sessions, project memory, goals, and optional backup API failover.
- ForceContext context receipts, token-budgeted memory retrieval, incremental project indexing, and verified response learning.
- Evidence-oriented Execution Kernel with local planning, structured debugging, verification gates, and confidence receipts.
- AI-selected read-only subagents for research, design, backend, frontend, testing, review, and security tasks.
- Explicit approval controls plus Smart Autopilot risk assessment for project mutations.

## Safety model

ForgeCode confines file tools to the selected project directory. Empty paths, project-root writes, directory paths, and path traversal are rejected. Writes are performed through verified UTF-8 temporary files and atomically replace the target only after validation.

Commands and file changes require confirmation by default. Smart Autopilot can approve clearly safe project work, while a deterministic safety layer blocks known destructive system operations. Full autopilot is available but should be enabled only in a disposable or version-controlled workspace.

API keys can be stored by the application, but environment variables are preferable for sensitive or shared machines. Never commit API keys, `.forgecode` project state, logs, or local configuration.

See [SECURITY.md](SECURITY.md) for reporting vulnerabilities and the supported-version policy.

## Requirements

- Windows 10 or later
- Python 3.10 or later, available as `py -3` or `python`
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
| Safety | `/autopilot smart\|on\|off`, `/doctor`, `/diagnostics`, `/logs` |
| Continuity | `/goal`, `/resume`, `/sessions`, `/session`, `/memory`, `/remember`, `/init` |
| ForceContext | `/force-context-init`, `/force-context-scan`, `/force-context-update`, `/force-memory-stats` |
| Execution engine | `/plan`, `/debug`, `/confidence`, `/engine` |
| Parallel work | `/agents`, `/agent`, `/delegate`, `/team`, `/batch` |
| Usage | `/status`, `/usage`, `/history`, `/context`, `/activity`, `/dashboard` |
| Help | `/help`, `/clear`, `/exit` |

Run `/help` for the complete command list and usage syntax.

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

## Provider configuration

ForgeCode includes presets for Anthropic, OpenAI, OpenRouter, Gemini, Groq, Mistral, DeepSeek, xAI, Together, Fireworks, Perplexity, Cerebras, SambaNova, NVIDIA NIM, Cohere, Kimchi, GitHub Models, Hugging Face, SiliconFlow, DashScope, Ollama, and LM Studio.

For a custom OpenAI-compatible or Anthropic-compatible endpoint:

```text
/provider custom
/connect https://your-service.example
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

`FORGECODE_HOME` can override the global settings directory. On first launch after upgrading, legacy Windows settings from `%USERPROFILE%\.forgecode` are copied to AppData when no AppData configuration exists; the legacy files are not deleted automatically.

Project-specific operational state stays in `<project>\.forgecode`. ForceContext project/session cards, its incremental index, and Context Receipts stay in `<project>\.force`. Both directories are ignored by Git.

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
