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

ForceSandbox is enabled by default. Model file tools operate in a private project copy. On Windows, generic commands run in an AppContainer process tree with a unique identity and execution workspace per project; Desktop, Documents, other projects, stored credentials, and other user data receive no access grant. The child receives no ForgeCode API key or inherited host environment. A read-only minimal Python runtime excludes host `site-packages`. Docker or Podman can still be selected explicitly and remain the automatic engines on non-Windows platforms. Missing isolation fails closed instead of falling back to the host shell. Common credentials, links, reparse points, and inaccessible OneDrive entries are not staged.

The ForgeCode controller itself remains a trusted host process: it contacts the configured provider, stores user settings, creates snapshots, mirrors files into the native execution workspace, performs conflict-checked transfers, and may run the argument-constrained ForceGraph bridge against the sandbox copy. Windows system binaries needed to start commands remain read-only and are not a hidden filesystem namespace. Internet-enabled sandboxes can still communicate with remote services, so untrusted dependencies and remote scripts remain supply-chain risks. Keep important projects under version control, use least-privilege keys, review sandbox logs and pending transfers, and report any host-path or secret exposure privately.
