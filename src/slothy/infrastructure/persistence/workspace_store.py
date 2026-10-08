"""桌面项目、任务归属与灵感的 SQLite 目录。"""

from contextlib import closing
from json import dumps, loads
from pathlib import Path
import sqlite3


class SQLiteWorkspaceCatalog:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("CREATE TABLE IF NOT EXISTS workspace_items (owner_id TEXT NOT NULL, kind TEXT NOT NULL, id TEXT NOT NULL, payload_json TEXT NOT NULL CHECK(json_valid(payload_json)), updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')), PRIMARY KEY(owner_id,kind,id))")

    def put(self, owner_id, kind, item_id, value):
        encoded = dumps(value, ensure_ascii=False, allow_nan=False)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("INSERT INTO workspace_items(owner_id,kind,id,payload_json) VALUES(?,?,?,?) ON CONFLICT(owner_id,kind,id) DO UPDATE SET payload_json=excluded.payload_json, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')", (owner_id, kind, item_id, encoded))

    def get(self, owner_id, kind, item_id):
        with closing(sqlite3.connect(self.path)) as connection:
            row = connection.execute("SELECT payload_json FROM workspace_items WHERE owner_id=? AND kind=? AND id=?", (owner_id, kind, item_id)).fetchone()
        return loads(row[0]) if row else None

    def list(self, owner_id, kind, *, limit=100):
        with closing(sqlite3.connect(self.path)) as connection:
            rows = connection.execute("SELECT payload_json FROM workspace_items WHERE owner_id=? AND kind=? ORDER BY updated_at DESC,id LIMIT ?", (owner_id, kind, limit)).fetchall()
        return [loads(row[0]) for row in rows]
