"""Schema versions for the SQLite stores: a fresh file and a file from
before versioning both end at the current version with their rows intact,
a later step runs once and atomically, a file from a newer release is
refused, and the backup is consistent while the store is open."""
from __future__ import annotations

import sqlite3
import threading

import pytest

from wirestudio import sqlite_store
from wirestudio.agent.session import SqliteSessionStore
from wirestudio.designs.store import SqliteDesignStore

GARAGE = {"schema_version": "0.3", "id": "garage", "name": "Garage", "board": {}, "components": []}


def _version(path) -> int:
    return sqlite_store.schema_version(path)


def test_fresh_files_are_at_the_current_version(tmp_path):
    SqliteDesignStore(tmp_path / "d.db")
    SqliteSessionStore(tmp_path / "s.db")
    assert _version(tmp_path / "d.db") == len(SqliteDesignStore.SCHEMA)
    assert _version(tmp_path / "s.db") == len(SqliteSessionStore.SCHEMA)


def test_a_file_from_before_versioning_is_adopted_with_its_rows(tmp_path):
    # The exact tables 0.40 created, with user_version left at 0.
    db = sqlite3.connect(tmp_path / "d.db")
    db.execute("CREATE TABLE IF NOT EXISTS designs ("
               "id TEXT PRIMARY KEY, document TEXT NOT NULL, saved_at TEXT NOT NULL)")
    db.execute("INSERT INTO designs VALUES ('old', ?, '2026-10-01T00:00:00+00:00')",
               ('{"schema_version": "0.3", "id": "old", "name": "Old", "board": {}, "components": []}',))
    db.commit()
    db.close()
    db = sqlite3.connect(tmp_path / "s.db")
    db.execute("CREATE TABLE IF NOT EXISTS messages ("
               "seq INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, "
               "role TEXT NOT NULL, content TEXT NOT NULL, timestamp TEXT NOT NULL)")
    db.execute("INSERT INTO messages (session_id, role, content, timestamp) "
               "VALUES ('s1', 'user', 'kept', '2026-10-01T00:00:00+00:00')")
    db.commit()
    db.close()
    assert _version(tmp_path / "d.db") == 0

    designs = SqliteDesignStore(tmp_path / "d.db")
    sessions = SqliteSessionStore(tmp_path / "s.db")
    assert _version(tmp_path / "d.db") == 1 and _version(tmp_path / "s.db") == 1
    assert designs.load("old")["name"] == "Old"
    assert sessions.load("s1")[0]["content"] == "kept"
    indexes = sqlite3.connect(tmp_path / "s.db").execute(
        "SELECT name FROM sqlite_master WHERE type = 'index'").fetchall()
    assert ("messages_session",) in indexes


def test_a_later_step_runs_once(tmp_path):
    path = tmp_path / "d.db"
    SqliteDesignStore(path).save(GARAGE)
    steps = SqliteDesignStore.SCHEMA + (("ALTER TABLE designs ADD COLUMN note TEXT",),)
    assert sqlite_store.migrate(path, "designs", steps) == 1
    assert sqlite_store.migrate(path, "designs", steps) == 2
    assert _version(path) == 2
    columns = [r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(designs)")]
    assert columns == ["id", "document", "saved_at", "note"]


def test_a_failing_step_leaves_the_file_as_it_was(tmp_path):
    path = tmp_path / "d.db"
    SqliteDesignStore(path).save(GARAGE)
    steps = SqliteDesignStore.SCHEMA + ((
        "ALTER TABLE designs ADD COLUMN note TEXT",
        "ALTER TABLE no_such_table ADD COLUMN x TEXT",
    ),)
    with pytest.raises(sqlite3.OperationalError):
        sqlite_store.migrate(path, "designs", steps)
    assert _version(path) == 1
    columns = [r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(designs)")]
    assert "note" not in columns
    assert SqliteDesignStore(path).load("garage")["name"] == "Garage"


def test_concurrent_openers_migrate_once(tmp_path):
    path = tmp_path / "d.db"
    SqliteDesignStore(path)
    steps = SqliteDesignStore.SCHEMA + (("ALTER TABLE designs ADD COLUMN note TEXT",),)
    errors: list[BaseException] = []

    def open_it():
        try:
            sqlite_store.migrate(path, "designs", steps)
        except BaseException as e:  # noqa: BLE001 - collected for the assert
            errors.append(e)

    threads = [threading.Thread(target=open_it) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert _version(path) == 2


def test_a_file_from_a_newer_release_is_refused(tmp_path):
    path = tmp_path / "d.db"
    SqliteDesignStore(path)
    db = sqlite3.connect(path)
    db.execute(f"PRAGMA user_version = {len(SqliteDesignStore.SCHEMA) + 1}")
    db.close()
    with pytest.raises(sqlite_store.StoreSchemaError, match="designs store at schema 2"):
        SqliteDesignStore(path)


def test_backup_is_consistent_while_the_store_is_in_use(tmp_path):
    path = tmp_path / "d.db"
    store = SqliteDesignStore(path)
    store.save(GARAGE)
    # An open connection keeps the write in the WAL rather than the main
    # file, which is what a plain copy would miss.
    held = sqlite_store.connect(path)
    held.execute("SELECT 1 FROM designs").fetchall()
    assert (tmp_path / "d.db-wal").exists()
    sqlite_store.backup(path, tmp_path / "backup" / "d.db")
    held.close()
    restored = SqliteDesignStore(tmp_path / "backup" / "d.db")
    assert restored.load("garage")["name"] == "Garage"
    assert _version(tmp_path / "backup" / "d.db") == 1


def test_cli(tmp_path, capsys):
    path = tmp_path / "s.db"
    SqliteSessionStore(path).append("s1", "user", "hello")
    assert sqlite_store.main(["version", str(path)]) == 0
    assert capsys.readouterr().out.strip() == "1"
    dest = tmp_path / "s.backup.db"
    assert sqlite_store.main(["backup", str(path), str(dest)]) == 0
    assert "(schema 1)" in capsys.readouterr().out
    assert SqliteSessionStore(dest).load("s1")[0]["content"] == "hello"
    assert sqlite_store.main(["backup", str(path), str(dest)]) == 2
    assert "refusing to overwrite" in capsys.readouterr().err
    assert sqlite_store.main(["version", str(tmp_path / "missing.db")]) == 2
