# Security Policy

## Supported versions

Security fixes are provided for the latest released version of ForgeCode. Older versions should be upgraded before a report is investigated.

## Reporting a vulnerability

Do not open a public issue for a vulnerability that could expose API keys, execute commands outside the selected project, bypass confirmation controls, or modify files outside the workspace.

Use GitHub's **Report a vulnerability** private security-advisory feature for the repository. Include:

- the ForgeCode version and Python/Windows versions;
- the smallest reproducible example;
- expected and actual behavior;
- the security impact;
- sanitized logs with all keys, tokens, private URLs, and personal paths removed.

Please allow maintainers reasonable time to validate and fix the issue before public disclosure.

## Security boundaries

ForgeCode sends prompts and selected project context to the configured AI provider. Provider security, retention, billing, and availability are governed by that provider. Review provider terms before sending proprietary code.

ForgeCode does not promise a perfect sandbox. Keep important projects under version control, review proposed operations, use least-privilege API keys, and avoid full autopilot outside disposable environments.
