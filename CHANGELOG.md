# Changelog

## 0.2.0

- Added a safer bridge entrypoint used by the Windows launcher.
- Changed public CLI behavior to safe JSON path rewriting by default.
- Added `--aggressive` for broader path-like JSON string rewriting.
- Added Codex SQLite schema validation before migration.
- Changed `archived_sessions` rollout discovery to recursive scanning.
- Added unmapped path samples and JSON key collision samples to counters.
- Added basic warning when Codex/OpenAI-related Windows processes appear to be running.
- Added `--version`.
- Added pytest coverage for path mapping, safe/aggressive mode, schema validation, archived rollout discovery, and dry-run behavior.
- Added GitHub Actions CI.
- Expanded README safety, privacy, and usage guidance.

## 0.1.0

- Initial public bridge script.
- Added dry-run by default, `--yes` apply mode, backup creation, and rollback.
