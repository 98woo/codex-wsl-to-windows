#!/usr/bin/env python3
"""Guarded public entrypoint for Codex Session Bridge.

This entrypoint uses the safe bridge and adds one more apply-time guard:
if JSON key collisions are detected during preflight analysis, `--yes` migration
is aborted before any backup or write operation starts.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SAFE_PATH = SCRIPT_DIR / "codex_session_path_bridge_all_win_safe.py"


def load_safe_bridge():
    spec = importlib.util.spec_from_file_location("codex_session_bridge_safe", SAFE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load safe bridge script: {SAFE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


safe = load_safe_bridge()
_original_migrate_all = safe.migrate_all


def guarded_migrate_all(args):
    safe.validate_db_schema(args.db)

    global_state = safe.legacy.load_global_state(args.db.parent)
    known_roots = safe.legacy.collect_known_windows_roots(global_state)
    counters = safe.Counters()

    safe.legacy.analyze_db(args, known_roots, counters)
    safe.legacy.analyze_rollouts(args, known_roots, counters)
    safe.legacy.analyze_global_state(args, known_roots, counters)

    if getattr(args, "yes", False) and counters.json_key_collisions:
        safe.legacy.die(
            "JSON key collision이 감지되어 실제 적용을 중단합니다. "
            "먼저 dry-run report를 확인하세요."
        )

    return _original_migrate_all(args)


def main(argv: list[str] | None = None) -> int:
    safe.migrate_all = guarded_migrate_all
    return safe.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
