"""SQLite 快照事务；显式实例化时才访问文件系统。"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from slothy.core.runtime.snapshot import (
    RuntimeSnapshot, SnapshotConflictError, SnapshotError,
)


class SQLiteSnapshotStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS runtime_snapshots "
                "(run_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, "
                "payload TEXT NOT NULL)"
            )

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def load(self, run_id: str):
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT payload FROM runtime_snapshots WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
            return RuntimeSnapshot.from_json(row[0]) if row else None
        except sqlite3.Error as error:
            raise SnapshotError("cannot load runtime snapshot") from error

    def save(self, snapshot, *, expected_revision):
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT revision FROM runtime_snapshots WHERE run_id = ?",
                    (snapshot.run_id,),
                ).fetchone()
                revision = row[0] if row else 0
                if revision != expected_revision:
                    raise SnapshotConflictError("snapshot revision has changed")
                prepared = snapshot.with_revision(revision + 1)
                connection.execute(
                    "INSERT INTO runtime_snapshots VALUES (?, ?, ?) "
                    "ON CONFLICT(run_id) DO UPDATE SET "
                    "revision=excluded.revision, payload=excluded.payload",
                    (snapshot.run_id, prepared.revision, prepared.to_json()),
                )
                return prepared
        except sqlite3.Error as error:
            raise SnapshotError("cannot save runtime snapshot") from error
