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

ForceSandbox is enabled by default. Model file tools operate in a private project copy and generic commands require Docker or Podman, with only that copy mounted into an ephemeral container. The container receives no ForgeCode API key or inherited host environment. Missing container isolation fails closed instead of falling back to the host shell. Common credentials, links, reparse points, and project metadata are not staged.

The ForgeCode controller itself remains a trusted host process: it contacts the configured provider, stores user settings, creates snapshots, performs conflict-checked transfers, and may run the argument-constrained ForceGraph bridge against the sandbox copy. Internet-enabled containers can still communicate with remote services, so untrusted dependencies and remote scripts remain supply-chain risks. Keep important projects under version control, use least-privilege keys, review sandbox logs and pending transfers, and report any host-path or secret exposure privately.
