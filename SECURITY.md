# Security Policy

## Supported versions

This repository currently supports the latest version on the `main` branch.

## Reporting a vulnerability

This tool reads and rewrites local Codex state files. Reports and backups can contain local usernames, project paths, session IDs, workspace roots, and permission roots.

If you find a security issue, please open a GitHub issue with the minimum information needed to reproduce the problem. Do not include real `.codex` databases, full reports, backups, tokens, or private project paths.

When sharing logs, redact:

- Windows usernames
- Linux usernames
- project paths
- session IDs
- account identifiers
- tokens or cookies
