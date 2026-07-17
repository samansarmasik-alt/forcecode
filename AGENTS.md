# Repository Guidelines

## Project Structure & Module Organization

ForgeCode deliberately keeps its runtime in `forgecode.py`, a dependency-free Python module containing providers, configuration, terminal UI, the Execution Kernel, workspace tools, and ForceContext. Windows launch and installation scripts live at the repository root. Tests are in `tests/test_forgecode.py`. User documentation and release notes are maintained in `README.md`, `CHANGELOG.md`, `SECURITY.md`, and `CONTRIBUTING.md`; architecture notes belong under `docs/`.

## Build, Test, and Development Commands

```powershell
py -3 forgecode.py --version
py -3 -m py_compile forgecode.py
py -3 -m unittest discover -s tests -v
.\forgecode.bat .
```

The first command checks the CLI entry point. Compilation catches syntax errors quickly. Run the complete `unittest` suite before submitting changes. The BAT command starts an interactive development session in the current repository.

## Coding Style & Naming Conventions

Use four-space indentation, type hints for public helpers, `snake_case` for functions and variables, `PascalCase` for classes, and uppercase names for constants. Prefer standard-library solutions; adding runtime dependencies conflicts with the project's lightweight design. Keep provider-specific behavior isolated and preserve UTF-8 handling on Windows. Use atomic file helpers for persistent data and never print secrets.

## Testing Guidelines

Tests use Python's built-in `unittest` and `unittest.mock`. Name test methods `test_<observable_behavior>`. Every bug fix needs a regression test, and provider changes should verify request payloads without live network calls. There is no fixed coverage threshold; changed branches and failure paths should be exercised.

## Commit & Pull Request Guidelines

Use concise, imperative commits such as `fix: preserve streamed tool output` or `feat: add context receipts`. This snapshot does not include repository history, so use these Conventional Commit prefixes consistently. Pull requests should explain user-visible behavior, list verification commands, link relevant issues, and include terminal screenshots when the UI changes.

## Security & Agent Instructions

Never commit API keys, `.forgecode/`, `.force/`, logs, or `force-memory-export.json`. Keep changes scoped, preserve existing Python/BAT behavior, and update documentation plus tests whenever commands or configuration change.
