#!/usr/bin/env python3
"""Bulk bridge WSL-recorded Codex sessions for Windows-native Codex App.

Run from Windows Python with Codex App and WSL Codex closed.

This tool can rewrite:
- state_5.sqlite threads cwd / rollout_path / sandbox_policy
- rollout JSONL session_meta.cwd and turn_context cwd/path fields
- .codex-global-state.json workspace roots and heartbeat permission roots

Default mode is dry-run. Add --yes to write changes. A rollback command restores
files from the generated backup directory.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import Any, Iterable

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
USER_HOME = Path(os.environ.get("USERPROFILE") or str(Path.home()))
STATE_DIR = USER_HOME / ".codex"
DEFAULT_DB = STATE_DIR / "state_5.sqlite"
DEFAULT_BACKUP_ROOT = PROJECT_DIR / "codex-session-bridge-backups"
DEFAULT_REPORT = PROJECT_DIR / "codex-session-bridge-all-report.json"

PATH_KEYS = {
    "cwd",
    "rollout_path",
    "writable_roots",
    "writableRoots",
    "active-workspace-roots",
    "electron-saved-workspace-roots",
    "project-order",
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


def die(message: str, code: int = 1) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(code)


def require_windows(force: bool) -> None:
    if os.name == "nt" or force:
        return
    die("이 스크립트는 Windows Python에서 실행해야 합니다. WSL에서 실행하려면 --force-non-windows가 필요합니다.")


def is_windows_drive_path(value: str) -> bool:
    return len(value) >= 3 and value[1] == ":" and value[2] in ("\\", "/")


def is_unc_path(value: str) -> bool:
    return value.startswith("\\\\")


def is_path_like(value: str) -> bool:
    normalized = value.replace("\\", "/")
    return (
        normalized.startswith("/mnt/")
        or normalized == "/home"
        or normalized.startswith("/home/")
        or is_windows_drive_path(value)
        or is_unc_path(value)
    )


def normalize_win_slashes(value: str) -> str:
    if is_unc_path(value):
        return "\\\\" + value[2:].replace("/", "\\")
    if is_windows_drive_path(value):
        return value[0].upper() + ":\\" + value[3:].replace("/", "\\")
    return value


def map_basic_path(value: str, distro: str) -> str | None:
    normalized = value.replace("\\", "/")
    if is_windows_drive_path(value) or is_unc_path(value):
        return normalize_win_slashes(value)
    if normalized.startswith("/mnt/") and len(normalized) >= 7 and normalized[6] == "/":
        drive = normalized[5].upper()
        rest = normalized[7:].replace("/", "\\")
        return f"{drive}:\\{rest}"
    if normalized == "/home" or normalized.startswith("/home/"):
        rest = normalized.lstrip("/").replace("/", "\\")
        return f"\\\\wsl.localhost\\{distro}\\{rest}"
    return None


def load_global_state(state_dir: Path) -> dict[str, Any] | None:
    path = state_dir / ".codex-global-state.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def collect_known_windows_roots(global_state: dict[str, Any] | None) -> list[str]:
    roots: list[str] = []
    if not isinstance(global_state, dict):
        return roots
    for key in ("electron-saved-workspace-roots", "project-order", "active-workspace-roots"):
        value = global_state.get(key)
        if isinstance(value, list):
            roots.extend(item for item in value if isinstance(item, str) and (is_windows_drive_path(item) or is_unc_path(item)))
    persisted = global_state.get("electron-persisted-atom-state")
    if isinstance(persisted, dict):
        hb = persisted.get("heartbeat-thread-permissions-by-id")
        if isinstance(hb, dict):
            for entry in hb.values():
                if not isinstance(entry, dict):
                    continue
                sandbox = entry.get("sandboxPolicy")
                if isinstance(sandbox, dict):
                    wr = sandbox.get("writableRoots")
                    if isinstance(wr, list):
                        roots.extend(item for item in wr if isinstance(item, str) and (is_windows_drive_path(item) or is_unc_path(item)))
    return sorted(set(normalize_win_slashes(root) for root in roots), key=len, reverse=True)


def apply_known_root_case(mapped: str, known_roots: list[str]) -> str:
    candidate = normalize_win_slashes(mapped)
    low = candidate.lower()
    for root in known_roots:
        root_norm = normalize_win_slashes(root)
        root_low = root_norm.lower()
        if low == root_low:
            return root_norm
        if low.startswith(root_low.rstrip("\\") + "\\"):
            return root_norm.rstrip("\\") + candidate[len(root_norm.rstrip("\\")):]
    return candidate


def get_long_path_name(path: str) -> str:
    if os.name != "nt" or is_unc_path(path):
        return path
    try:
        import ctypes
        from ctypes import wintypes
        GetLongPathNameW = ctypes.windll.kernel32.GetLongPathNameW
        GetLongPathNameW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
        GetLongPathNameW.restype = wintypes.DWORD
        size = GetLongPathNameW(path, None, 0)
        if size == 0:
            return path
        buf = ctypes.create_unicode_buffer(size + 1)
        result = GetLongPathNameW(path, buf, size + 1)
        if result == 0:
            return path
        return buf.value
    except Exception:
        return path


def map_path(value: str | None, distro: str, known_roots: list[str]) -> str | None:
    if value is None:
        return None
    if value == "":
        return value
    mapped = map_basic_path(value, distro)
    if mapped is None:
        return None
    mapped = apply_known_root_case(mapped, known_roots)
    mapped = get_long_path_name(mapped)
    mapped = apply_known_root_case(mapped, known_roots)
    return mapped


def should_map_string(key: str | None, value: str) -> bool:
    if not is_path_like(value):
        return False
    if key in PATH_KEYS:
        return True
    if value.startswith("/mnt/") or value.startswith("/home/") or value == "/home":
        return True
    if is_windows_drive_path(value) or is_unc_path(value):
        return True
    return False


def map_json(value: Any, distro: str, known_roots: list[str], counters: Counters, key: str | None = None) -> tuple[Any, bool]:
    if isinstance(value, str):
        if not should_map_string(key, value):
            return value, False
        mapped = map_path(value, distro, known_roots)
        if mapped is None:
            counters.unmapped_paths += 1
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
            if isinstance(item_key, str) and is_path_like(item_key):
                mapped_key = map_path(item_key, distro, known_roots)
                if mapped_key and mapped_key != item_key:
                    new_key = mapped_key
                    changed = True
                    counters.json_string_paths_changed += 1
            new_value, value_changed = map_json(item_value, distro, known_roots, counters, item_key)
            changed = changed or value_changed
            new_obj[new_key] = new_value
        return new_obj, changed
    return value, False


def iter_rollout_files(state_dir: Path, include_archived: bool) -> Iterable[Path]:
    sessions = state_dir / "sessions"
    if sessions.exists():
        yield from sorted(sessions.rglob("rollout-*.jsonl"))
    archived = state_dir / "archived_sessions"
    if include_archived and archived.exists():
        yield from sorted(archived.glob("rollout-*.jsonl"))


def read_first_line_json(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as f:
            line = f.readline()
    except OSError:
        return None
    if not line:
        return None
    try:
        parsed = json.loads(line)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def thread_id_from_rollout(path: Path) -> str | None:
    first = read_first_line_json(path)
    payload = first.get("payload") if isinstance(first, dict) else None
    tid = payload.get("id") if isinstance(payload, dict) else None
    return tid if isinstance(tid, str) else None


def copy_backup_file(source: Path, backup_dir: Path, state_dir: Path) -> None:
    if not source.exists():
        return
    try:
        rel = source.relative_to(state_dir.parent)
    except ValueError:
        rel = Path(source.name)
    target = backup_dir / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def make_backup(args: argparse.Namespace, changed_rollouts: list[Path], report: dict[str, Any]) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = args.backup_root / f"{stamp}-all-sessions"
    backup_dir.mkdir(parents=True, exist_ok=False)
    state_dir = args.db.parent
    for suffix in ("", "-wal", "-shm"):
        source = Path(str(args.db) + suffix)
        copy_backup_file(source, backup_dir, state_dir)
    for name in (".codex-global-state.json", "session_index.jsonl"):
        copy_backup_file(state_dir / name, backup_dir, state_dir)
    for rollout in changed_rollouts:
        copy_backup_file(rollout, backup_dir, state_dir)
    (backup_dir / "migration-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return backup_dir


def connect(db: Path, readonly: bool = False) -> sqlite3.Connection:
    if not db.exists():
        die(f"DB 파일을 찾을 수 없습니다: {db}")
    if readonly:
        conn = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    return conn


def analyze_db(args: argparse.Namespace, known_roots: list[str], counters: Counters) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    with connect(args.db, readonly=True) as conn:
        rows = conn.execute("SELECT id,cwd,rollout_path,sandbox_policy FROM threads ORDER BY updated_at DESC").fetchall()
    counters.db_threads_seen = len(rows)
    for row in rows:
        new_cwd = map_path(row["cwd"], args.distro, known_roots)
        new_rollout = map_path(row["rollout_path"], args.distro, known_roots)
        sandbox = row["sandbox_policy"]
        new_sandbox = sandbox
        sandbox_changed = False
        if sandbox:
            try:
                parsed = json.loads(sandbox)
                mapped, sandbox_changed = map_json(parsed, args.distro, known_roots, counters)
                if sandbox_changed:
                    new_sandbox = json.dumps(mapped, ensure_ascii=False, separators=(",", ":"))
            except json.JSONDecodeError:
                pass
        if new_cwd is None:
            new_cwd = row["cwd"]
        if new_rollout is None:
            new_rollout = row["rollout_path"]
        if new_cwd != row["cwd"] or new_rollout != row["rollout_path"] or new_sandbox != sandbox:
            counters.db_threads_changed += 1
            changes.append({
                "id": row["id"],
                "old_cwd": row["cwd"],
                "new_cwd": new_cwd,
                "old_rollout_path": row["rollout_path"],
                "new_rollout_path": new_rollout,
                "old_sandbox_policy": sandbox,
                "new_sandbox_policy": new_sandbox,
            })
    return changes


def analyze_rollouts(args: argparse.Namespace, known_roots: list[str], counters: Counters) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for path in iter_rollout_files(args.db.parent, args.include_archived):
        counters.rollout_files_seen += 1
        changed_lines = 0
        first_old_cwd = None
        first_new_cwd = None
        try:
            with path.open("r", encoding="utf-8") as f:
                for index, line in enumerate(f, start=1):
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    mapped, changed = map_json(event, args.distro, known_roots, counters)
                    if changed:
                        changed_lines += 1
                        if first_old_cwd is None:
                            payload = event.get("payload") if isinstance(event, dict) else None
                            if isinstance(payload, dict) and isinstance(payload.get("cwd"), str):
                                first_old_cwd = payload.get("cwd")
                            new_payload = mapped.get("payload") if isinstance(mapped, dict) else None
                            if isinstance(new_payload, dict) and isinstance(new_payload.get("cwd"), str):
                                first_new_cwd = new_payload.get("cwd")
        except OSError:
            continue
        if changed_lines:
            counters.rollout_files_changed += 1
            changes.append({
                "path": str(path),
                "thread_id": thread_id_from_rollout(path),
                "changed_lines": changed_lines,
                "first_old_cwd": first_old_cwd,
                "first_new_cwd": first_new_cwd,
            })
    return changes


def analyze_global_state(args: argparse.Namespace, known_roots: list[str], counters: Counters) -> dict[str, Any] | None:
    path = args.db.parent / ".codex-global-state.json"
    if not path.exists():
        return None
    try:
        old = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    mapped, changed = map_json(old, args.distro, known_roots, counters)
    counters.global_state_changed = bool(changed)
    if not changed:
        return None
    return {"path": str(path), "new_json": mapped}


def write_rollout(path: Path, args: argparse.Namespace, known_roots: list[str], counters: Counters) -> None:
    output: list[str] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            stripped = line.rstrip("\n")
            try:
                event = json.loads(stripped)
            except json.JSONDecodeError:
                output.append(line)
                continue
            mapped, changed = map_json(event, args.distro, known_roots, counters)
            if changed:
                output.append(json.dumps(mapped, ensure_ascii=False, separators=(",", ":")) + "\n")
            else:
                output.append(line)
    path.write_text("".join(output), encoding="utf-8")


def apply_db_changes(args: argparse.Namespace, db_changes: list[dict[str, Any]]) -> None:
    with connect(args.db) as conn:
        conn.execute("PRAGMA busy_timeout = 5000")
        for item in db_changes:
            conn.execute(
                "UPDATE threads SET cwd=?, rollout_path=?, sandbox_policy=? WHERE id=?",
                (item["new_cwd"], item["new_rollout_path"], item["new_sandbox_policy"], item["id"]),
            )
        conn.commit()


def rollback(args: argparse.Namespace) -> int:
    backup = args.backup
    if not backup.exists() or not backup.is_dir():
        die(f"backup 디렉토리를 찾을 수 없습니다: {backup}")
    state_dir = args.db.parent
    backup_state = backup / state_dir.name
    if not backup_state.exists():
        die(f"backup 형식이 맞지 않습니다: {backup_state} 없음")
    if not args.yes:
        print(f"DRY RUN only. 롤백하려면 --yes를 추가하세요: {backup}")
        return 0
    for source in backup_state.rglob("*"):
        if source.is_file():
            rel = source.relative_to(backup_state)
            target = state_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    print(f"ROLLED BACK: {backup}")
    return 0


def migrate_all(args: argparse.Namespace) -> int:
    global_state = load_global_state(args.db.parent)
    known_roots = collect_known_windows_roots(global_state)
    counters = Counters()
    db_changes = analyze_db(args, known_roots, counters)
    rollout_changes = analyze_rollouts(args, known_roots, counters)
    global_change = analyze_global_state(args, known_roots, counters)

    report = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "db": str(args.db),
        "include_archived": args.include_archived,
        "known_windows_roots": known_roots,
        "counters": counters.__dict__,
        "db_changes_sample": db_changes[:20],
        "rollout_changes_sample": rollout_changes[:20],
        "global_state_changed": bool(global_change),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({
        "report": str(args.report),
        "counters": counters.__dict__,
        "db_changes": len(db_changes),
        "rollout_changes": len(rollout_changes),
        "global_state_changed": bool(global_change),
    }, ensure_ascii=False, indent=2))

    if not args.yes:
        print("DRY RUN only. 전체 변환하려면 같은 명령에 --yes를 추가하세요.")
        return 0

    changed_rollouts = [Path(item["path"]) for item in rollout_changes]
    backup = make_backup(args, changed_rollouts, report)
    apply_db_changes(args, db_changes)
    write_counters = Counters()
    for rollout in changed_rollouts:
        write_rollout(rollout, args, known_roots, write_counters)
    if global_change:
        global_path = Path(global_change["path"])
        global_path.write_text(json.dumps(global_change["new_json"], ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"MIGRATED ALL")
    print(f"BACKUP: {backup}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--backup-root", type=Path, default=DEFAULT_BACKUP_ROOT)
    parser.add_argument("--distro", default="Ubuntu")
    parser.add_argument("--force-non-windows", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    all_parser = sub.add_parser("migrate-all", help="모든 mappable WSL 세션 경로를 Windows 경로로 변환")
    all_parser.add_argument("--include-archived", action="store_true", help="archived_sessions rollout도 변환")
    all_parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    all_parser.add_argument("--yes", action="store_true")
    all_parser.set_defaults(func=migrate_all)

    rb = sub.add_parser("rollback", help="migrate-all 백업에서 복원")
    rb.add_argument("--backup", type=Path, required=True)
    rb.add_argument("--yes", action="store_true")
    rb.set_defaults(func=rollback)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    require_windows(args.force_non_windows)
    return args.func(args)


def run_guarded_entrypoint(argv: list[str] | None = None) -> int:
    """Delegate direct legacy execution to the guarded public entrypoint."""
    guarded_path = Path(__file__).resolve().with_name("codex_session_path_bridge_all_win_guarded.py")
    if not guarded_path.exists():
        print(
            "WARNING: guarded entrypoint was not found; running the legacy implementation directly.",
            file=sys.stderr,
        )
        return main(argv)

    spec = importlib.util.spec_from_file_location("codex_session_bridge_guarded_entrypoint", guarded_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load guarded bridge script: {guarded_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.main(argv)


if __name__ == "__main__":
    raise SystemExit(run_guarded_entrypoint())
