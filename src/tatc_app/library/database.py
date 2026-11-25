"""
Storage of the designs and analysis runs that users save, in a SQLite
database (a file, see `TATC_DATABASE`). Every operation is scoped to one
user: users never read or change each other's records.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import json
import os
import sqlite3
import threading
import uuid
from contextlib import closing
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()

# the version of the database schema (`PRAGMA user_version`)
SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS designs (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    data TEXT NOT NULL,
    created TEXT NOT NULL,
    updated TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS designs_by_user ON designs (user_id, updated);
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    analysis TEXT NOT NULL,
    request TEXT NOT NULL,
    design TEXT NOT NULL,
    summary TEXT,
    created TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS runs_by_user ON runs (user_id, created);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _count_satellites(data: str) -> int:
    satellites = json.loads(data).get("satellites")
    return len(satellites) if isinstance(satellites, list) else 0


class Library:
    """
    The saved designs and analysis runs of users.
    """

    def __init__(self, path: str):
        """
        Args:
            path (str): The path of the database file (created, with its
                directory, on first use).
        """
        self.path = path
        self._lock = threading.Lock()
        self._ready = False

    def _connect(self) -> sqlite3.Connection:
        """
        Opens a connection, creating the database on first use.
        """
        with self._lock:
            if not self._ready:
                directory = os.path.dirname(os.path.abspath(self.path))
                os.makedirs(directory, exist_ok=True)
                with closing(sqlite3.connect(self.path, timeout=10)) as connection:
                    connection.execute("PRAGMA journal_mode=WAL")
                    connection.executescript(SCHEMA)
                    connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                    connection.commit()
                self._ready = True
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _query(self, sql: str, parameters: tuple = ()) -> List[sqlite3.Row]:
        with closing(self._connect()) as connection:
            return connection.execute(sql, parameters).fetchall()

    def _execute(self, sql: str, parameters: tuple = ()) -> int:
        with closing(self._connect()) as connection:
            with connection:
                return connection.execute(sql, parameters).rowcount

    def count(self, table: str, user_id: str) -> int:
        """
        Counts the records of a user in a table (`designs` or `runs`).
        """
        if table not in ("designs", "runs"):
            raise ValueError(f"Unknown table: {table}")
        rows = self._query(
            f"SELECT COUNT(*) AS n FROM {table} WHERE user_id = ?", (user_id,)
        )
        return rows[0]["n"]

    # --- Designs ---

    @staticmethod
    def _design(row: sqlite3.Row, include_data: bool) -> Dict[str, Any]:
        design = {
            "id": row["id"],
            "name": row["name"],
            "created": row["created"],
            "updated": row["updated"],
            "satellites": _count_satellites(row["data"]),
        }
        if include_data:
            design["design"] = json.loads(row["data"])
        return design

    def list_designs(self, user_id: str) -> List[Dict[str, Any]]:
        """
        Lists the designs of a user (without their data), latest first.
        """
        rows = self._query(
            "SELECT * FROM designs WHERE user_id = ? ORDER BY updated DESC",
            (user_id,),
        )
        return [self._design(row, False) for row in rows]

    def get_design(self, user_id: str, design_id: str) -> Optional[Dict[str, Any]]:
        """
        Gets a design of a user (with its data), or `None` if not found.
        """
        rows = self._query(
            "SELECT * FROM designs WHERE user_id = ? AND id = ?", (user_id, design_id)
        )
        return self._design(rows[0], True) if rows else None

    def create_design(self, user_id: str, name: str, data: dict) -> Dict[str, Any]:
        """
        Saves a new design of a user.
        """
        design_id = str(uuid.uuid4())
        now = _now()
        self._execute(
            "INSERT INTO designs (id, user_id, name, data, created, updated) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (design_id, user_id, name, json.dumps(data), now, now),
        )
        return self.get_design(user_id, design_id)

    def update_design(
        self, user_id: str, design_id: str, name: str, data: dict
    ) -> Optional[Dict[str, Any]]:
        """
        Replaces a design of a user, or returns `None` if not found.
        """
        updated = self._execute(
            "UPDATE designs SET name = ?, data = ?, updated = ? "
            "WHERE user_id = ? AND id = ?",
            (name, json.dumps(data), _now(), user_id, design_id),
        )
        return self.get_design(user_id, design_id) if updated else None

    def delete_design(self, user_id: str, design_id: str) -> bool:
        """
        Deletes a design of a user, returning whether it was found.
        """
        return (
            self._execute(
                "DELETE FROM designs WHERE user_id = ? AND id = ?",
                (user_id, design_id),
            )
            > 0
        )

    # --- Runs ---

    @staticmethod
    def _run(row: sqlite3.Row, include_inputs: bool) -> Dict[str, Any]:
        run = {
            "id": row["id"],
            "name": row["name"],
            "analysis": row["analysis"],
            "created": row["created"],
            "summary": None if row["summary"] is None else json.loads(row["summary"]),
        }
        if include_inputs:
            run["request"] = json.loads(row["request"])
            run["design"] = json.loads(row["design"])
        return run

    def list_runs(
        self, user_id: str, analysis: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Lists the runs of a user (with their summaries, without their
        inputs), latest first, optionally of one analysis.
        """
        if analysis is None:
            rows = self._query(
                "SELECT * FROM runs WHERE user_id = ? ORDER BY created DESC",
                (user_id,),
            )
        else:
            rows = self._query(
                "SELECT * FROM runs WHERE user_id = ? AND analysis = ? "
                "ORDER BY created DESC",
                (user_id, analysis),
            )
        return [self._run(row, False) for row in rows]

    def get_run(self, user_id: str, run_id: str) -> Optional[Dict[str, Any]]:
        """
        Gets a run of a user (with its inputs), or `None` if not found.
        """
        rows = self._query(
            "SELECT * FROM runs WHERE user_id = ? AND id = ?", (user_id, run_id)
        )
        return self._run(rows[0], True) if rows else None

    def create_run(
        self,
        user_id: str,
        name: str,
        analysis: str,
        request: dict,
        design: dict,
        summary: Optional[dict],
    ) -> Dict[str, Any]:
        """
        Saves a new run of a user.
        """
        run_id = str(uuid.uuid4())
        self._execute(
            "INSERT INTO runs (id, user_id, name, analysis, request, design, "
            "summary, created) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                user_id,
                name,
                analysis,
                json.dumps(request),
                json.dumps(design),
                None if summary is None else json.dumps(summary),
                _now(),
            ),
        )
        return self.get_run(user_id, run_id)

    def rename_run(
        self, user_id: str, run_id: str, name: str
    ) -> Optional[Dict[str, Any]]:
        """
        Renames a run of a user, or returns `None` if not found.
        """
        updated = self._execute(
            "UPDATE runs SET name = ? WHERE user_id = ? AND id = ?",
            (name, user_id, run_id),
        )
        return self.get_run(user_id, run_id) if updated else None

    def delete_run(self, user_id: str, run_id: str) -> bool:
        """
        Deletes a run of a user, returning whether it was found.
        """
        return (
            self._execute(
                "DELETE FROM runs WHERE user_id = ? AND id = ?", (user_id, run_id)
            )
            > 0
        )


# the library of the server
library = Library(os.getenv("TATC_DATABASE", os.path.join("data", "tatc-app.db")))
