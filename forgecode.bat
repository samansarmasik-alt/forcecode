# Contributing to ForgeCode

Thank you for helping improve ForgeCode. Keep changes focused, behavior-preserving, and easy to review.

## Before you start

1. Search existing issues before opening a new one.
2. For a substantial behavioral change, open an issue and describe the motivation first.
3. Never include real API keys, private endpoints, user logs, or `.forgecode` state in an issue, test, commit, or pull request.

## Development setup

ForgeCode requires Python 3.10 or later and has no third-party runtime dependencies.

```powershell
python forgecode.py --version
python -m unittest discover -s tests -v
```

The existing `forgecode.py`, `forgecode.bat`, and global `Force` installation flow are compatibility surfaces. Avoid moving or renaming them without a migration plan and corresponding Windows tests.

## Pull requests

- Keep each pull request limited to one concern.
- Preserve default confirmation and workspace-boundary behavior.
- Add tests for fixes and user-visible behavior changes.
- Update README or CHANGELOG when commands, configuration, or compatibility changes.
- Use UTF-8 without a byte-order mark for text files.
- Run syntax checks and the full test suite before submitting.

By contributing, you agree that your contribution is licensed under the MIT License.
