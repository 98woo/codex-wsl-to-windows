# Contributing

Thanks for improving Codex Session Bridge.

## Local checks

```bash
python -m pip install pytest
python -m py_compile tools/codex_session_path_bridge_all_win.py
python -m py_compile tools/codex_session_path_bridge_all_win_safe.py
python -m pytest -q
```

## Safety rules

This project modifies local Codex state files. Changes should prefer safe, reversible behavior.

When adding migration behavior:

1. Keep dry-run as the default.
2. Add tests before broadening rewrite behavior.
3. Avoid rewriting user/model conversation text unless the user opts in.
4. Include rollback compatibility.
5. Do not commit real `.codex` data, migration reports, or backups.
