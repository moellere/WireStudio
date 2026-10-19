"""Schema versions, migration and backup for the SQLite stores.

Each SQLite store owns an ordered tuple of steps; step `i` takes the
database from `PRAGMA user_version` `i` to `i + 1`. A database written
before versioning reads 0 and already holds the tables, so every store's
step 0 is its original `CREATE ... IF NOT EXISTS`: a no-op there, the
whole schema on a fresh file. A step runs in one transaction with the
version bump, under a write lock, and the version is read inside that
lock, so two processes opening the same file migrate it once.

A database whose version is past the last step was written by a newer
release. Opening it raises rather than reading tables this code does not
know; restore the backup taken before the upgrade, or run the newer
release.

`python -m wirestudio.sqlite_store version <db>` prints a file's version;
`backup <db> <dest>` copies it through SQLite's online backup, which is
consistent while the studio is running (a plain `cp` of a WAL database
is not).
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Sequence

Step = Sequence[str]


class StoreSchemaError(RuntimeError):
    """The database was written by a newer release than this one."""


def connect(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path, timeout=10)
    db.execute("PRAGMA journal_mode=WAL")
    return db


def schema_version(path: Path) -> int:
    db = sqlite3.connect(path, timeout=10)
    try:
        return db.execute("PRAGMA user_version").fetchone()[0]
    finally:
        db.close()


def migrate(path: Path, store: str, steps: Sequence[Step]) -> int:
    """Bring the database at `path` to `len(steps)`. Returns the version
    it was at before."""
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10, isolation_level=None)
    try:
        db.execute("PRAGMA journal_mode=WAL")
        before = None
        while True:
            db.execute("BEGIN IMMEDIATE")
            try:
                version = db.execute("PRAGMA user_version").fetchone()[0]
                if before is None:
                    before = version
                if version > len(steps):
                    raise StoreSchemaError(
                        f"{path} is the {store} store at schema {version}, written by a newer "
                        f"release; this one reads up to {len(steps)}")
                if version == len(steps):
                    db.execute("COMMIT")
                    return before
                for statement in steps[version]:
                    db.execute(statement)
                db.execute(f"PRAGMA user_version = {version + 1}")
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise
    finally:
        db.close()


def backup(source: Path, dest: Path) -> None:
    if not source.exists():
        raise FileNotFoundError(f"no database at {source}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(source, timeout=10)
    out = sqlite3.connect(dest)
    try:
        src.backup(out)
    finally:
        out.close()
        src.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_version = sub.add_parser("version", help="print a database's schema version")
    p_version.add_argument("db", type=Path)
    p_backup = sub.add_parser("backup", help="copy a database consistently while it is in use")
    p_backup.add_argument("db", type=Path)
    p_backup.add_argument("dest", type=Path)
    args = parser.parse_args(argv)
    if not args.db.exists():
        print(f"no database at {args.db}", file=sys.stderr)
        return 2
    if args.cmd == "version":
        print(schema_version(args.db))
        return 0
    if args.dest.exists():
        print(f"{args.dest} exists; refusing to overwrite it", file=sys.stderr)
        return 2
    backup(args.db, args.dest)
    print(f"{args.db} -> {args.dest} (schema {schema_version(args.dest)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
