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

<!-- vi3ecode:plugin:graphify:guidance:begin -->
## Graphify code intelligence (active)

The `vi3ecode-graphify` MCP server serves this project's code graph: modules,
dependencies, communities, and PR impact. Tools: query_graph, get_node,
get_neighbors, get_community, shortest_path, god_nodes, graph_stats, list_prs,
get_pr_impact, triage_prs. If your harness defers or hides MCP tools, load them
first (tool search for "graphify") instead of assuming they are missing.

Make the graph your first investigation step, not a fallback:
- Before any repo-wide text search (grep/glob over unknown files), run
  query_graph on the symbol or path, then get_neighbors for its callers and
  dependents.
- Before editing a module others may import — including while fixing a failing
  test or reviewing a diff — check get_neighbors to scope the blast radius; use
  get_pr_impact or triage_prs for branch/PR-level work.
- For architecture, ownership, or "where does X live" questions, start from
  query_graph, get_community, god_nodes, or graph_stats.

Treat graph results as a map: verify the relevant source files before editing
because source code remains authoritative. Skip the graph only when the task
already names the exact files and nothing else depends on the lines you change.
If you finish a multi-file task without a single Graphify query, state in one
line why the graph was not needed. If the server is unavailable or stale,
continue from source and say so. Never run Graphify build or update commands
yourself; Vi3ecode owns graph maintenance.
<!-- vi3ecode:plugin:graphify:guidance:end -->
