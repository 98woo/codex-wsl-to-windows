from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from argparse import Namespace
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "codex_session_path_bridge_all_win_safe.py"


def load_bridge():
    spec = importlib.util.spec_from_file_location("bridge_safe", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.patch_legacy()
    return module


bridge = load_bridge()


def test_map_basic_mnt_drive_path():
    assert bridge.map_basic_path("/mnt/c/Users/foo/project", "Ubuntu") == r"C:\Users\foo\project"


def test_map_basic_mnt_drive_root():
    assert bridge.map_basic_path("/mnt/d", "Ubuntu") == "D:\\"


def test_map_basic_rejects_invalid_mnt_drive():
    assert bridge.map_basic_path("/mnt/1/project", "Ubuntu") is None


def test_map_basic_home_path():
    assert bridge.map_basic_path("/home/woo/project", "Ubuntu") == (
        r"\\wsl.localhost\Ubuntu\home\woo\project"
    )


def test_safe_mode_does_not_rewrite_message_text():
    bridge.AGGRESSIVE = False
    counters = bridge.Counters()
    event = {"type": "message", "payload": {"text": "/home/woo/project"}}

    mapped, changed = bridge.map_json(event, "Ubuntu", [], counters)

    assert changed is False
    assert mapped["payload"]["text"] == "/home/woo/project"


def test_safe_mode_rewrites_metadata_cwd():
    bridge.AGGRESSIVE = False
    counters = bridge.Counters()
    event = {"type": "session_meta", "payload": {"cwd": "/home/woo/project"}}

    mapped, changed = bridge.map_json(event, "Ubuntu", [], counters)

    assert changed is True
    assert mapped["payload"]["cwd"] == r"\\wsl.localhost\Ubuntu\home\woo\project"


def test_aggressive_mode_rewrites_message_text():
    bridge.AGGRESSIVE = True
    counters = bridge.Counters()
    event = {"type": "message", "payload": {"text": "/home/woo/project"}}

    mapped, changed = bridge.map_json(event, "Ubuntu", [], counters)

    bridge.AGGRESSIVE = False
    assert changed is True
    assert mapped["payload"]["text"] == r"\\wsl.localhost\Ubuntu\home\woo\project"


def test_iter_rollout_files_includes_nested_archived(tmp_path: Path):
    state_dir = tmp_path / ".codex"
    nested_session = state_dir / "sessions" / "2026" / "05"
    nested_archive = state_dir / "archived_sessions" / "2026" / "05"
    nested_session.mkdir(parents=True)
    nested_archive.mkdir(parents=True)

    session_file = nested_session / "rollout-session.jsonl"
    archive_file = nested_archive / "rollout-archived.jsonl"
    session_file.write_text("{}\n", encoding="utf-8")
    archive_file.write_text("{}\n", encoding="utf-8")

    found = list(bridge.iter_rollout_files(state_dir, include_archived=True))

    assert session_file in found
    assert archive_file in found


def test_json_key_collision_is_reported_without_overwrite():
    counters = bridge.Counters()
    obj = {
        r"C:\project": {"existing": True},
        "/mnt/c/project": {"migrated": True},
    }

    mapped, changed = bridge.map_json(obj, "Ubuntu", [], counters)

    assert changed is False
    assert counters.json_key_collisions == 1
    assert mapped[r"C:\project"] == {"existing": True}
    assert mapped["/mnt/c/project"] == {"migrated": True}


def make_db(path: Path, include_updated_at: bool = True) -> None:
    columns = """
        id TEXT,
        cwd TEXT,
        rollout_path TEXT,
        sandbox_policy TEXT
    """
    if include_updated_at:
        columns += ", updated_at INTEGER"

    with sqlite3.connect(path) as conn:
        conn.execute(f"CREATE TABLE threads ({columns})")
        if include_updated_at:
            conn.execute(
                """
                INSERT INTO threads(id, cwd, rollout_path, sandbox_policy, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "thread-1",
                    "/mnt/c/project",
                    "/mnt/c/Users/foo/.codex/sessions/rollout-1.jsonl",
                    json.dumps({"writableRoots": ["/mnt/c/project"]}),
                    1,
                ),
            )
        conn.commit()


def test_validate_db_schema_accepts_expected_schema(tmp_path: Path):
    db = tmp_path / "state_5.sqlite"
    make_db(db)

    bridge.validate_db_schema(db)


def test_validate_db_schema_rejects_missing_column(tmp_path: Path):
    db = tmp_path / "state_5.sqlite"
    make_db(db, include_updated_at=False)

    with pytest.raises(SystemExit):
        bridge.validate_db_schema(db)


def test_migrate_all_dry_run_does_not_modify_db(tmp_path: Path):
    state_dir = tmp_path / ".codex"
    state_dir.mkdir()
    db = state_dir / "state_5.sqlite"
    make_db(db)

    report = tmp_path / "report.json"
    args = Namespace(
        db=db,
        backup_root=tmp_path / "backups",
        distro="Ubuntu",
        force_non_windows=True,
        include_archived=False,
        report=report,
        aggressive=False,
        yes=False,
    )

    result = bridge.migrate_all(args)

    assert result == 0
    assert report.exists()

    with sqlite3.connect(db) as conn:
        cwd = conn.execute("SELECT cwd FROM threads WHERE id='thread-1'").fetchone()[0]
    assert cwd == "/mnt/c/project"

    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["counters"]["db_threads_changed"] == 1
