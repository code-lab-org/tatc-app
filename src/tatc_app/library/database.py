"""
Storage of the designs and analysis runs that users save, in a SQLite
database (a file, see `TATC_DATABASE`). Every operation is scoped to one
user: users never read or change each other's records. Runs may be saved
under a design (deleting the design deletes them).

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

# the version of the database schema (`PRAGMA user_version`): 2 saves runs
# under designs
SCHEMA_VERSION = 2

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
    created TEXT NOT NULL,
    design_id TEXT
);
CREATE INDEX IF NOT EXISTS runs_by_user ON runs (user_id, created);
"""

# migrations of databases of earlier versions of the schema (whose tables
# `SCHEMA` does not change), by the version they migrate to
MIGRATIONS = {
    2: ["ALTER TABLE runs ADD COLUMN design_id TEXT"],
}

# indexes of columns that migrations may add
INDEXES = """
CREATE INDEX IF NOT EXISTS runs_by_design ON runs (user_id, design_id);
"""

# columns of designs (`d`) without their data, with their numbers of
# satellites (counted by SQLite, so listing designs does not read and parse
# the data of each) and runs
DESIGN_COLUMNS = (
    "d.id, d.name, d.created, d.updated, "
    "COALESCE(json_array_length(d.data, '$.satellites'), 0) AS satellites, "
    "(SELECT COUNT(*) FROM runs r WHERE r.user_id = d.user_id "
    "AND r.design_id = d.id) AS runs"
)

# columns of runs without their inputs (`request` and `design`)
RUN_COLUMNS = "id, name, analysis, design_id, created, summary"

# a field of an update left unchanged
UNCHANGED = object()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def migrate(connection: sqlite3.Connection) -> None:
    """
    Creates the tables of a database, or migrates them from an earlier
    version of the schema.
    """
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    # a database without tables gets the latest schema
    new = not connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'runs'"
    ).fetchall()
    with connection:
        connection.executescript(SCHEMA)
        if not new:
            for target in range(max(version, 1) + 1, SCHEMA_VERSION + 1):
                for statement in MIGRATIONS.get(target, []):
                    connection.execute(statement)
        connection.executescript(INDEXES)
        connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")


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
        Opens a connection, creating (or migrating) the database on first use.
        """
        with self._lock:
            if not self._ready:
                directory = os.path.dirname(os.path.abspath(self.path))
                os.makedirs(directory, exist_ok=True)
                with closing(sqlite3.connect(self.path, timeout=10)) as connection:
                    connection.execute("PRAGMA journal_mode=WAL")
                    migrate(connection)
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
            "satellites": row["satellites"],
            "runs": row["runs"],
        }
        if include_data:
            design["design"] = json.loads(row["data"])
        return design

    def list_designs(self, user_id: str) -> List[Dict[str, Any]]:
        """
        Lists the designs of a user (without their data, with their numbers
        of runs), latest first.
        """
        rows = self._query(
            f"SELECT {DESIGN_COLUMNS} FROM designs d WHERE d.user_id = ? "
            "ORDER BY d.updated DESC",
            (user_id,),
        )
        return [self._design(row, False) for row in rows]

    def get_design(self, user_id: str, design_id: str) -> Optional[Dict[str, Any]]:
        """
        Gets a design of a user (with its data), or `None` if not found.
        """
        rows = self._query(
            f"SELECT {DESIGN_COLUMNS}, d.data FROM designs d "
            "WHERE d.user_id = ? AND d.id = ?",
            (user_id, design_id),
        )
        return self._design(rows[0], True) if rows else None

    def has_design(self, user_id: str, design_id: str) -> bool:
        """
        Tests whether a user has a design.
        """
        rows = self._query(
            "SELECT 1 FROM designs WHERE user_id = ? AND id = ?", (user_id, design_id)
        )
        return bool(rows)

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
        Deletes a design of a user and the runs saved under it, returning
        whether it was found.
        """
        with closing(self._connect()) as connection:
            with connection:
                deleted = connection.execute(
                    "DELETE FROM designs WHERE user_id = ? AND id = ?",
                    (user_id, design_id),
                ).rowcount
                if deleted:
                    connection.execute(
                        "DELETE FROM runs WHERE user_id = ? AND design_id = ?",
                        (user_id, design_id),
                    )
        return deleted > 0

    # --- Runs ---

    @staticmethod
    def _run(row: sqlite3.Row, include_inputs: bool) -> Dict[str, Any]:
        run = {
            "id": row["id"],
            "name": row["name"],
            "analysis": row["analysis"],
            "design_id": row["design_id"],
            "created": row["created"],
            "summary": None if row["summary"] is None else json.loads(row["summary"]),
        }
        if include_inputs:
            run["request"] = json.loads(row["request"])
            run["design"] = json.loads(row["design"])
        return run

    def list_runs(
        self,
        user_id: str,
        analysis: Optional[str] = None,
        design_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Lists the runs of a user (with their summaries, without their
        inputs), latest first, optionally of one analysis or saved under one
        design.
        """
        sql = f"SELECT {RUN_COLUMNS} FROM runs WHERE user_id = ?"
        parameters = [user_id]
        if analysis is not None:
            sql += " AND analysis = ?"
            parameters.append(analysis)
        if design_id is not None:
            sql += " AND design_id = ?"
            parameters.append(design_id)
        rows = self._query(sql + " ORDER BY created DESC", tuple(parameters))
        return [self._run(row, False) for row in rows]

    def get_run(self, user_id: str, run_id: str) -> Optional[Dict[str, Any]]:
        """
        Gets a run of a user (with its inputs), or `None` if not found.
        """
        rows = self._query(
            f"SELECT {RUN_COLUMNS}, request, design FROM runs "
            "WHERE user_id = ? AND id = ?",
            (user_id, run_id),
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
        design_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Saves a new run of a user, optionally under a design.
        """
        run_id = str(uuid.uuid4())
        self._execute(
            "INSERT INTO runs (id, user_id, name, analysis, request, design, "
            "summary, created, design_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                user_id,
                name,
                analysis,
                json.dumps(request),
                json.dumps(design),
                None if summary is None else json.dumps(summary),
                _now(),
                design_id,
            ),
        )
        return self.get_run(user_id, run_id)

    def update_run(
        self,
        user_id: str,
        run_id: str,
        name: Any = UNCHANGED,
        design_id: Any = UNCHANGED,
    ) -> Optional[Dict[str, Any]]:
        """
        Renames a run of a user, or saves it under another design (or none);
        returns `None` if not found.
        """
        changes = {
            column: value
            for column, value in (("name", name), ("design_id", design_id))
            if value is not UNCHANGED
        }
        if changes:
            assignments = ", ".join(f"{column} = ?" for column in changes)
            found = self._execute(
                f"UPDATE runs SET {assignments} WHERE user_id = ? AND id = ?",
                (*changes.values(), user_id, run_id),
            )
            if not found:
                return None
        return self.get_run(user_id, run_id)

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
