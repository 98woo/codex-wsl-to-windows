#!/usr/bin/env python3
"""Safer entrypoint for Codex Session Bridge.

This wrapper keeps the legacy one-file implementation importable while adding
safer defaults for public use:
- safe JSON path rewriting by default
- optional --aggressive mode
- recursive archived_sessions scanning
- SQLite schema validation
- unmapped path/key-collision samples in reports
- basic process warning before writes
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import io
import os
import sqlite3
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

VERSION = '0.2.0'
BS = chr(92)
SCRIPT_DIR = Path(__file__).resolve().parent
LEGACY_PATH = SCRIPT_DIR / 'codex_session_path_bridge_all_win.py'
AGGRESSIVE = False

SAFE_PATH_KEYS = {
    'cwd',
    'rollout_path',
    'writable_roots',
    'writableRoots',
    'active-workspace-roots',
    'electron-saved-workspace-roots',
    'project-order',
    'path',
    'root',
    'workspaceRoot',
    'workspace_root',
}


@dataclass
class Counters:
    db_threads_seen: int = 0
    db_threads_changed: int = 0
    rollout_files_seen: int = 0
    rollout_files_changed: int = 0
    global_state_changed: bool = False
    json_string_paths_changed: int = 0
    unmapped_paths: int = 0
    unmapped_path_samples: list[str] = field(default_factory=list)
    json_key_collisions: int = 0
    json_key_collision_samples: list[dict[str, str]] = field(default_factory=list)


def load_legacy():
    spec = importlib.util.spec_from_file_location('codex_session_bridge_legacy', LEGACY_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'Cannot load legacy bridge script: {LEGACY_PATH}')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


legacy = load_legacy()


def is_windows_drive_path(value: str) -> bool:
    return len(value) >= 3 and value[1] == ':' and value[2] in (BS, '/')


def is_unc_path(value: str) -> bool:
    return value.startswith(BS + BS)


def normalize_win_slashes(value: str) -> str:
    if is_unc_path(value):
        return BS + BS + value[2:].replace('/', BS)
    if is_windows_drive_path(value):
        return value[0].upper() + ':' + BS + value[3:].replace('/', BS)
    return value


def map_basic_path(value: str, distro: str) -> str | None:
    normalized = value.replace(BS, '/')
    if is_windows_drive_path(value) or is_unc_path(value):
        return normalize_win_slashes(value)

    if normalized.startswith('/mnt/'):
        parts = normalized.split('/', 3)
        if len(parts) >= 3 and len(parts[2]) == 1 and parts[2].isalpha():
            drive = parts[2].upper()
            if len(parts) == 3:
                return drive + ':' + BS
            return drive + ':' + BS + parts[3].replace('/', BS)
        return None

    if normalized == '/home' or normalized.startswith('/home/'):
        rest = normalized.lstrip('/').replace('/', BS)
        return BS + BS + 'wsl.localhost' + BS + distro + BS + rest

    return None


def should_map_string(key: str | None, value: str) -> bool:
    if not legacy.is_path_like(value):
        return False
    if key in SAFE_PATH_KEYS:
        return True
    return AGGRESSIVE


def record_unmapped(counters: Counters, value: str) -> None:
    counters.unmapped_paths += 1
    if len(counters.unmapped_path_samples) < 20:
        counters.unmapped_path_samples.append(value)


def record_collision(counters: Counters, old_key: str, new_key: str) -> None:
    counters.json_key_collisions += 1
    if len(counters.json_key_collision_samples) < 20:
        counters.json_key_collision_samples.append({'old_key': old_key, 'new_key': new_key})


def map_json(value: Any, distro: str, known_roots: list[str], counters: Counters, key: str | None = None) -> tuple[Any, bool]:
    if isinstance(value, str):
        if not should_map_string(key, value):
            return value, False
        mapped = legacy.map_path(value, distro, known_roots)
        if mapped is None:
            record_unmapped(counters, value)
            return value, False
        if mapped != value:
            counters.json_string_paths_changed += 1
            return mapped, True
        return value, False

    if isinstance(value, list):
        changed = False
        new_items = []
        for item in value:
            new_item, item_changed = map_json(item, distro, known_roots, counters, key)
            changed = changed or item_changed
            new_items.append(new_item)
        return new_items, changed

    if isinstance(value, dict):
        changed = False
        new_obj: dict[str, Any] = {}
        for item_key, item_value in value.items():
            new_key = item_key
            if isinstance(item_key, str) and legacy.is_path_like(item_key):
                mapped_key = legacy.map_path(item_key, distro, known_roots)
                if mapped_key and mapped_key != item_key:
                    if mapped_key in new_obj:
                        record_collision(counters, item_key, mapped_key)
                    else:
                        new_key = mapped_key
                        changed = True
                        counters.json_string_paths_changed += 1
            new_value, value_changed = map_json(item_value, distro, known_roots, counters, item_key)
            changed = changed or value_changed
            new_obj[new_key] = new_value
        return new_obj, changed

    return value, False


def iter_rollout_files(state_dir: Path, include_archived: bool) -> Iterable[Path]:
    sessions = state_dir / 'sessions'
    if sessions.exists():
        yield from sorted(sessions.rglob('rollout-*.jsonl'))

    archived = state_dir / 'archived_sessions'
    if include_archived and archived.exists():
        yield from sorted(archived.rglob('rollout-*.jsonl'))


def validate_db_schema(db: Path) -> None:
    required = {'id', 'cwd', 'rollout_path', 'sandbox_policy', 'updated_at'}
    with legacy.connect(db, readonly=True) as conn:
        tables = {row['name'] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'threads' not in tables:
            legacy.die('지원하지 않는 Codex DB 스키마입니다: threads 테이블이 없습니다.')
        columns = {row['name'] for row in conn.execute('PRAGMA table_info(threads)')}

    missing = required - columns
    if missing:
        legacy.die('지원하지 않는 Codex DB 스키마입니다. threads 테이블에 필요한 컬럼이 없습니다: ' + repr(sorted(missing)))


def find_possible_codex_processes() -> list[str]:
    if os.name != 'nt':
        return []
    try:
        completed = subprocess.run(['tasklist', '/FO', 'CSV', '/NH'], capture_output=True, text=True, timeout=5, check=False)
    except Exception:
        return []
    if completed.returncode != 0:
        return []

    matches: set[str] = set()
    for row in csv.reader(io.StringIO(completed.stdout)):
        if not row:
            continue
        name = row[0].strip()
        low = name.lower()
        if 'codex' in low or 'openai' in low:
            matches.add(name)
    return sorted(matches)


def warn_if_codex_may_be_running() -> None:
    processes = find_possible_codex_processes()
    if processes:
        print('WARNING: Codex/OpenAI 관련 프로세스가 실행 중일 수 있습니다. Codex App과 WSL Codex를 종료한 뒤 실행하는 것을 권장합니다.', file=sys.stderr)
        print('WARNING: detected processes: ' + ', '.join(processes), file=sys.stderr)


def migrate_all(args: argparse.Namespace) -> int:
    validate_db_schema(args.db)
    if args.yes:
        warn_if_codex_may_be_running()
    result = legacy.migrate_all(args)
    return result


def rollback(args: argparse.Namespace) -> int:
    if args.yes:
        warn_if_codex_may_be_running()
    return legacy.rollback(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Bridge WSL-recorded Codex sessions for Windows-native Codex App.')
    parser.add_argument('--version', action='version', version=f'%(prog)s {VERSION}')
    parser.add_argument('--db', type=Path, default=legacy.DEFAULT_DB)
    parser.add_argument('--backup-root', type=Path, default=legacy.DEFAULT_BACKUP_ROOT)
    parser.add_argument('--distro', default='Ubuntu')
    parser.add_argument('--force-non-windows', action='store_true')
    sub = parser.add_subparsers(dest='command', required=True)

    all_parser = sub.add_parser('migrate-all', help='모든 mappable WSL 세션 경로를 Windows 경로로 변환')
    all_parser.add_argument('--include-archived', action='store_true', help='archived_sessions rollout도 변환')
    all_parser.add_argument('--report', type=Path, default=legacy.DEFAULT_REPORT)
    all_parser.add_argument('--aggressive', action='store_true', help='대화 원문까지 포함해 경로처럼 보이는 모든 문자열을 변환합니다.')
    all_parser.add_argument('--yes', action='store_true')
    all_parser.set_defaults(func=migrate_all)

    rb = sub.add_parser('rollback', help='migrate-all 백업에서 복원')
    rb.add_argument('--backup', type=Path, required=True)
    rb.add_argument('--yes', action='store_true')
    rb.set_defaults(func=rollback)
    return parser


def patch_legacy() -> None:
    legacy.VERSION = VERSION
    legacy.PATH_KEYS = SAFE_PATH_KEYS
    legacy.Counters = Counters
    legacy.map_basic_path = map_basic_path
    legacy.should_map_string = lambda key, value: should_map_string(key, value)
    legacy.map_json = map_json
    legacy.iter_rollout_files = iter_rollout_files


def main(argv: list[str] | None = None) -> int:
    global AGGRESSIVE
    legacy.require_windows('--force-non-windows' in (argv if argv is not None else sys.argv[1:]))
    patch_legacy()
    parser = build_parser()
    args = parser.parse_args(argv)
    AGGRESSIVE = bool(getattr(args, 'aggressive', False))
    return args.func(args)


if __name__ == '__main__':
    raise SystemExit(main())
