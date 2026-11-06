"""Small SQLite repository; connection scope is one operation."""

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from typing import Any, Dict, Iterator, List, Optional, Union


class Store:
    def __init__(self, path: Optional[Union[str, Path]] = None) -> None:
        self.path = Path(path or os.environ.get("WORKBENCH_DB", "data/workbench.sqlite3"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS artifacts (id TEXT PRIMARY KEY, kind TEXT NOT NULL, created TEXT NOT NULL, payload TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS run_index (id TEXT PRIMARY KEY, created TEXT NOT NULL, filename TEXT NOT NULL, dataset_id TEXT NOT NULL, summary TEXT NOT NULL)"
            )

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(str(self.path), timeout=30)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def save(self, kind: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        identity = uuid4().hex
        created = datetime.now(timezone.utc).isoformat()
        value = {**payload, "id": identity, "created": created}
        with self.connect() as db:
            db.execute(
                "INSERT INTO artifacts VALUES (?, ?, ?, ?)",
                (identity, kind, created, json.dumps(value, ensure_ascii=False)),
            )
            if kind == "run":
                db.execute(
                    "INSERT INTO run_index VALUES (?, ?, ?, ?, ?)",
                    (
                        identity,
                        created,
                        value["filename"],
                        value.get("dataset_id", ""),
                        json.dumps(value["summary"]),
                    ),
                )
        return value

    def get(self, kind: str, identity: str) -> Optional[Dict[str, Any]]:
        with self.connect() as db:
            row = db.execute(
                "SELECT payload FROM artifacts WHERE id = ? AND kind = ?", (identity, kind)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def history(self) -> List[Dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT id, created, filename, dataset_id, summary FROM run_index ORDER BY created DESC LIMIT 20"
            ).fetchall()
        return [
            {
                "id": row[0],
                "created": row[1],
                "filename": row[2],
                "dataset_id": row[3],
                "summary": json.loads(row[4]),
            }
            for row in rows
        ]
