from __future__ import annotations

import csv
import io
import math
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
OPEN_STATUSES = ("Pending", "Scheduled", "Draft Scheduled", "Final Scheduled", "In progress", "Active", "On Hold", "Overdue")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def as_bool(value: Any) -> int:
    return 1 if bool(value) else 0


class CompatRow(dict):
    """Mapping row that also supports the legacy row[0] access pattern."""

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class CursorAdapter:
    def __init__(self, cursor):
        self.cursor = cursor

    @staticmethod
    def _row(value):
        if value is None:
            return None
        if isinstance(value, dict):
            return CompatRow(value)
        try:
            return CompatRow(dict(value))
        except (TypeError, ValueError):
            return value

    def fetchone(self):
        return self._row(self.cursor.fetchone())

    def fetchall(self):
        return [self._row(row) for row in self.cursor.fetchall()]

    def __iter__(self):
        for row in self.cursor:
            yield self._row(row)


class ConnectionAdapter:
    """Small SQL compatibility layer for SQLite and PostgreSQL."""

    def __init__(self, connection, backend: str):
        self.connection = connection
        self.backend = backend

    def _sql(self, statement: str) -> str:
        return statement.replace("?", "%s") if self.backend == "postgresql" else statement

    def execute(self, statement: str, params: Iterable[Any] = ()):
        cursor = self.connection.cursor()
        cursor.execute(self._sql(statement), tuple(params))
        return CursorAdapter(cursor)

    def executemany(self, statement: str, rows: Iterable[Iterable[Any]]):
        cursor = self.connection.cursor()
        cursor.executemany(self._sql(statement), rows)
        return CursorAdapter(cursor)

    def executescript(self, script: str):
        if self.backend == "sqlite":
            self.connection.executescript(script)
            return
        for statement in script.split(";"):
            if statement.strip():
                self.execute(statement)

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()

    def close(self):
        self.connection.close()


class Database:
    def __init__(
        self,
        path: str | Path | None = None,
        database_url: str | None = None,
    ):
        configured_url = database_url or os.getenv("DATABASE_URL", "").strip()
        self.startup_warning = ""
        if configured_url:
            try:
                import psycopg  # noqa: F401
                from psycopg.rows import dict_row  # noqa: F401
            except ImportError:
                self.startup_warning = (
                    "DATABASE_URL is configured, but the PostgreSQL driver is not installed. "
                    "The app started in temporary SQLite mode. Add psycopg[binary]>=3.3,<4 "
                    "to requirements.txt and reboot."
                )
                configured_url = ""
        self.database_url = configured_url or None
        self.backend = "postgresql" if self.database_url else "sqlite"
        if self.database_url:
            self.backend_label = "Managed PostgreSQL"
        elif self.startup_warning:
            self.backend_label = "Temporary SQLite fallback"
        else:
            self.backend_label = "Local SQLite"
        self.path = Path(path or "data/maintainly.db")
        if self.backend == "sqlite":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self):
        if self.backend == "postgresql":
            try:
                import psycopg
                from psycopg.rows import dict_row
            except ImportError as exc:
                raise RuntimeError(
                    "PostgreSQL is configured but psycopg is not installed. "
                    "Install the packages in requirements.txt."
                ) from exc
            raw_connection = psycopg.connect(self.database_url, row_factory=dict_row)
        else:
            raw_connection = sqlite3.connect(self.path, timeout=30)
            raw_connection.row_factory = sqlite3.Row
            raw_connection.execute("PRAGMA foreign_keys = ON")
            raw_connection.execute("PRAGMA journal_mode = WAL")
        connection = ConnectionAdapter(raw_connection, self.backend)
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS team_members (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    email TEXT UNIQUE,
                    availability TEXT NOT NULL DEFAULT 'Available',
                    color TEXT NOT NULL DEFAULT '#2563eb',
                    skill TEXT NOT NULL DEFAULT 'Mechanical',
                    weekly_hours REAL NOT NULL DEFAULT 40,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS team_crews (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    members TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS assets (
                    id TEXT PRIMARY KEY,
                    asset_number TEXT NOT NULL UNIQUE,
                    asset_name TEXT NOT NULL,
                    location TEXT NOT NULL DEFAULT '',
                    department TEXT NOT NULL DEFAULT 'Operations',
                    criticality TEXT NOT NULL DEFAULT 'Normal',
                    manufacturer TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL DEFAULT '',
                    active INTEGER NOT NULL DEFAULT 1,
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS work_orders (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    asset TEXT NOT NULL,
                    location TEXT NOT NULL,
                    due_at TEXT NOT NULL,
                    priority TEXT NOT NULL DEFAULT 'Medium',
                    status TEXT NOT NULL DEFAULT 'Pending',
                    technician TEXT NOT NULL DEFAULT 'Unassigned',
                    duration_hours REAL NOT NULL DEFAULT 1,
                    category TEXT NOT NULL DEFAULT 'General',
                    notes TEXT NOT NULL DEFAULT '',
                    department TEXT NOT NULL DEFAULT 'Operations',
                    mechanical_manpower INTEGER NOT NULL DEFAULT 0,
                    welding_manpower INTEGER NOT NULL DEFAULT 0,
                    crew_size_required INTEGER NOT NULL DEFAULT 1,
                    priority_score INTEGER NOT NULL DEFAULT 7,
                    allowed_days TEXT NOT NULL DEFAULT 'Monday,Tuesday,Wednesday,Thursday,Friday',
                    preferred_day TEXT NOT NULL DEFAULT '',
                    earliest_start_day TEXT NOT NULL DEFAULT '',
                    latest_finish_day TEXT NOT NULL DEFAULT '',
                    weekend_allowed INTEGER NOT NULL DEFAULT 0,
                    requires_shutdown INTEGER NOT NULL DEFAULT 0,
                    fixed_day_job INTEGER NOT NULL DEFAULT 0,
                    can_split_across_days INTEGER NOT NULL DEFAULT 1,
                    scope_ready INTEGER NOT NULL DEFAULT 1,
                    parts_ready INTEGER NOT NULL DEFAULT 1,
                    permits_ready INTEGER NOT NULL DEFAULT 1,
                    shutdown_ready INTEGER NOT NULL DEFAULT 1,
                    ready_to_schedule INTEGER NOT NULL DEFAULT 1,
                    completed_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS schedule_assignments (
                    id TEXT PRIMARY KEY,
                    work_order_id TEXT NOT NULL REFERENCES work_orders(id) ON DELETE CASCADE,
                    schedule_state TEXT NOT NULL DEFAULT 'Draft',
                    day TEXT NOT NULL,
                    team_label TEXT NOT NULL,
                    assigned_technicians TEXT NOT NULL DEFAULT '',
                    assigned_hours REAL NOT NULL DEFAULT 1,
                    required_crew_size INTEGER NOT NULL DEFAULT 1,
                    mechanical_manpower INTEGER NOT NULL DEFAULT 0,
                    welding_manpower INTEGER NOT NULL DEFAULT 0,
                    priority TEXT NOT NULL DEFAULT 'Medium',
                    priority_score INTEGER NOT NULL DEFAULT 7,
                    location TEXT NOT NULL DEFAULT '',
                    department TEXT NOT NULL DEFAULT 'Operations',
                    notes TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'Scheduled',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS schedule_history (
                    id TEXT PRIMARY KEY,
                    assignment_id TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    old_value TEXT NOT NULL DEFAULT '',
                    new_value TEXT NOT NULL DEFAULT '',
                    changed_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS app_migrations (
                    name TEXT PRIMARY KEY,
                    applied_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_work_status ON work_orders(status);
                CREATE INDEX IF NOT EXISTS idx_work_due ON work_orders(due_at);
                CREATE INDEX IF NOT EXISTS idx_schedule_state ON schedule_assignments(schedule_state);
                CREATE INDEX IF NOT EXISTS idx_schedule_day ON schedule_assignments(day);
                """
            )
            email_column = next((column for column in self._table_columns(conn, "team_members") if column["name"] == "email"), None)
            if self.backend == "sqlite" and email_column and email_column.get("notnull"):
                conn.executescript(
                    """
                    ALTER TABLE team_members RENAME TO team_members_required_email;
                    CREATE TABLE team_members (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        role TEXT NOT NULL,
                        email TEXT UNIQUE,
                        availability TEXT NOT NULL DEFAULT 'Available',
                        color TEXT NOT NULL DEFAULT '#2563eb',
                        skill TEXT NOT NULL DEFAULT 'Mechanical',
                        weekly_hours REAL NOT NULL DEFAULT 40,
                        active INTEGER NOT NULL DEFAULT 1,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    INSERT INTO team_members (
                        id, name, role, email, availability, color, skill, weekly_hours,
                        active, created_at, updated_at
                    )
                    SELECT
                        id, name, role, NULLIF(TRIM(email), ''), availability, color, skill,
                        weekly_hours, active, created_at, updated_at
                    FROM team_members_required_email;
                    DROP TABLE team_members_required_email;
                    """
                )
            elif self.backend == "postgresql" and email_column and email_column.get("notnull"):
                conn.execute("ALTER TABLE team_members ALTER COLUMN email DROP NOT NULL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS crew_memberships (
                    crew_id TEXT NOT NULL REFERENCES team_crews(id) ON DELETE CASCADE,
                    member_id TEXT NOT NULL UNIQUE REFERENCES team_members(id) ON DELETE CASCADE,
                    position INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (crew_id, member_id)
                );
                CREATE INDEX IF NOT EXISTS idx_crew_memberships_crew ON crew_memberships(crew_id);
                """
            )
            self._ensure_column(conn, "schedule_assignments", "crew_id", "crew_id TEXT REFERENCES team_crews(id) ON DELETE SET NULL")
            self._ensure_column(conn, "schedule_assignments", "scheduled_date", "scheduled_date TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "schedule_assignments", "start_at", "start_at TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "schedule_assignments", "end_at", "end_at TEXT NOT NULL DEFAULT ''")
            conn.execute(
                """CREATE INDEX IF NOT EXISTS idx_schedule_date
                   ON schedule_assignments(scheduled_date)"""
            )
            conn.execute(
                """UPDATE schedule_assignments
                   SET crew_id=(SELECT id FROM team_crews WHERE name=schedule_assignments.team_label)
                   WHERE crew_id IS NULL"""
            )
            self._migrate_crew_memberships(conn)
            self._backfill_assignment_times(conn)
            self._remove_sample_jobs(conn)
            self._seed(conn)

    def _table_columns(self, conn: ConnectionAdapter, table: str) -> list[dict[str, Any]]:
        if self.backend == "sqlite":
            return self._dicts(conn.execute(f"PRAGMA table_info({table})").fetchall())
        return self._dicts(
            conn.execute(
                """SELECT column_name AS name,
                          CASE WHEN is_nullable='NO' THEN 1 ELSE 0 END AS notnull
                   FROM information_schema.columns
                   WHERE table_schema=current_schema() AND table_name=?""",
                (table,),
            ).fetchall()
        )

    def _ensure_column(self, conn: ConnectionAdapter, table: str, column: str, definition: str) -> None:
        if column not in {row["name"] for row in self._table_columns(conn, table)}:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")

    def _migrate_crew_memberships(self, conn: ConnectionAdapter) -> None:
        migration = "normalize_crew_memberships_v1"
        if conn.execute("SELECT 1 FROM app_migrations WHERE name=?", (migration,)).fetchone():
            return
        assigned = {
            row["member_id"]
            for row in conn.execute("SELECT member_id FROM crew_memberships").fetchall()
        }
        for crew in conn.execute("SELECT id,members FROM team_crews ORDER BY created_at,name").fetchall():
            for position, member_id in enumerate(str(crew["members"] or "").split(",")):
                member_id = member_id.strip()
                if not member_id or member_id in assigned:
                    continue
                if conn.execute("SELECT 1 FROM team_members WHERE id=?", (member_id,)).fetchone():
                    conn.execute(
                        "INSERT INTO crew_memberships (crew_id,member_id,position) VALUES (?,?,?)",
                        (crew["id"], member_id, position),
                    )
                    assigned.add(member_id)
        conn.execute("INSERT INTO app_migrations VALUES (?,?)", (migration, now_iso()))

    def _backfill_assignment_times(self, conn: ConnectionAdapter) -> None:
        for row in conn.execute(
            """SELECT id,day,assigned_hours,scheduled_date,start_at,end_at
               FROM schedule_assignments
               WHERE scheduled_date='' OR start_at='' OR end_at=''"""
        ).fetchall():
            scheduled_date, start_at, end_at = self._time_values(
                row["day"], float(row["assigned_hours"])
            )
            conn.execute(
                """UPDATE schedule_assignments
                   SET scheduled_date=?,start_at=?,end_at=? WHERE id=?""",
                (scheduled_date, start_at, end_at, row["id"]),
            )

    @staticmethod
    def _remove_sample_jobs(conn: sqlite3.Connection) -> None:
        migration = "remove_builtin_sample_work_orders_v1"
        if conn.execute("SELECT 1 FROM app_migrations WHERE name=?", (migration,)).fetchone():
            return
        sample_filter = """
            (w.id='WO-2842' AND w.title='Generator load bank test') OR
            (w.id='WO-2848' AND w.title='Chiller water sample') OR
            (w.id='WO-2850' AND w.title='Conveyor belt alignment') OR
            (w.id='WO-2854' AND w.title='Dock frame weld repair')
        """
        conn.execute(
            f"""DELETE FROM schedule_history WHERE assignment_id IN (
                SELECT a.id FROM schedule_assignments a
                JOIN work_orders w ON w.id=a.work_order_id
                WHERE {sample_filter}
            )"""
        )
        conn.execute(
            f"""DELETE FROM schedule_assignments WHERE work_order_id IN (
                SELECT w.id FROM work_orders w WHERE {sample_filter}
            )"""
        )
        conn.execute(f"DELETE FROM work_orders AS w WHERE {sample_filter}")
        conn.execute("INSERT INTO app_migrations VALUES (?,?)", (migration, now_iso()))

    def _seed(self, conn: sqlite3.Connection) -> None:
        now = now_iso()
        if conn.execute("SELECT COUNT(*) FROM team_members").fetchone()[0] == 0:
            members = [
                ("TM-MAYA", "Maya Chen", "Senior technician", "maya@maintainly.local", "Available", "#2563eb", "Mechanical", 40, 1),
                ("TM-JORDAN", "Jordan Lee", "Electrical technician", "jordan@maintainly.local", "Available", "#d7905c", "Electrical / Mechanical", 40, 1),
                ("TM-SAM", "Sam Rivera", "Maintenance technician", "sam@maintainly.local", "Available", "#5c7fd7", "Multi-skill", 40, 1),
                ("TM-AMARA", "Amara Brown", "Welder", "amara@maintainly.local", "Available", "#8b6fba", "Welding", 40, 1),
            ]
            conn.executemany(
                "INSERT INTO team_members VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [(*row, now, now) for row in members],
            )
        if conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 0:
            assets = [
                ("AS-AHU04", "AHU-04", "Air Handler 04", "Building A - Roof", "Facilities", "High", "Trane", "TAM9", 1, "Primary building air handler"),
                ("AS-GEN02", "GEN-02", "Backup Generator 02", "Utility yard", "Utilities", "Critical", "Caterpillar", "C18", 1, "Monthly readiness testing required"),
                ("AS-DOCK07", "DOCK-07", "Dock Door 07", "Warehouse - Bay 7", "Warehouse", "High", "Rite-Hite", "RHH-5000", 1, "Safety interlocks installed"),
                ("AS-CH01", "CH-01", "Process Chiller 01", "Central plant", "Utilities", "Critical", "York", "YVAA", 1, "Water treatment readings required"),
            ]
            conn.executemany(
                "INSERT INTO assets VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                [(*row, now, now) for row in assets],
            )

    @staticmethod
    def _dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
        return [dict(row) for row in rows]

    def list_team(self, active_only: bool = False) -> list[dict[str, Any]]:
        query = "SELECT * FROM team_members"
        if active_only:
            query += " WHERE active=1"
        query += " ORDER BY name"
        with self.connect() as conn:
            return self._dicts(conn.execute(query).fetchall())

    def save_team_member(self, data: dict[str, Any], member_id: str | None = None) -> str:
        member_id = member_id or new_id("TM")
        now = now_iso()
        email = str(data.get("email", "") or "").strip().lower() or None
        values = (
            str(data.get("name", "")).strip(),
            str(data.get("role", "Maintenance technician")).strip(),
            email,
            str(data.get("availability", "Available")),
            str(data.get("color", "#2563eb")),
            str(data.get("skill", "Mechanical")),
            max(1.0, float(data.get("weekly_hours", 40))),
            as_bool(data.get("active", True)),
            now,
        )
        if not values[0]:
            raise ValueError("Name is required.")
        with self.connect() as conn:
            if conn.execute("SELECT 1 FROM team_members WHERE id=?", (member_id,)).fetchone():
                conn.execute(
                    """UPDATE team_members SET name=?,role=?,email=?,availability=?,color=?,skill=?,weekly_hours=?,active=?,updated_at=? WHERE id=?""",
                    (*values, member_id),
                )
            else:
                conn.execute(
                    """INSERT INTO team_members (id,name,role,email,availability,color,skill,weekly_hours,active,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (member_id, *values[:-1], now, now),
                )
        return member_id

    def delete_team_member(self, member_id: str) -> None:
        with self.connect() as conn:
            member = conn.execute("SELECT name FROM team_members WHERE id=?", (member_id,)).fetchone()
            if member:
                conn.execute("UPDATE work_orders SET technician='Unassigned' WHERE technician=?", (member["name"],))
                crew_rows = conn.execute(
                    "SELECT crew_id FROM crew_memberships WHERE member_id=?",
                    (member_id,),
                ).fetchall()
                conn.execute("DELETE FROM team_members WHERE id=?", (member_id,))
                for crew in crew_rows:
                    remaining = self._crew_people(conn, crew["crew_id"])
                    if not remaining:
                        conn.execute(
                            """UPDATE schedule_assignments
                               SET assigned_technicians='',updated_at=?
                               WHERE crew_id=? AND status!='Complete'""",
                            (now_iso(), crew["crew_id"]),
                        )
                        conn.execute("DELETE FROM team_crews WHERE id=?", (crew["crew_id"],))
                    else:
                        conn.execute(
                            """UPDATE schedule_assignments
                               SET assigned_technicians=?,updated_at=?
                               WHERE crew_id=? AND status!='Complete'""",
                            (
                                ",".join(person["name"] for person in remaining),
                                now_iso(),
                                crew["crew_id"],
                            ),
                        )

    def list_crews(self, active_only: bool = False) -> list[dict[str, Any]]:
        query = "SELECT * FROM team_crews"
        if active_only:
            query += " WHERE active=1"
        query += " ORDER BY name"
        with self.connect() as conn:
            crews = self._dicts(conn.execute(query).fetchall())
            for crew in crews:
                crew["members"] = ",".join(
                    row["member_id"]
                    for row in conn.execute(
                        """SELECT member_id FROM crew_memberships
                           WHERE crew_id=? ORDER BY position,member_id""",
                        (crew["id"],),
                    ).fetchall()
                )
            return crews

    @staticmethod
    def _crew_people(conn: ConnectionAdapter, crew_id: str) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in conn.execute(
                """SELECT m.* FROM crew_memberships cm
                   JOIN team_members m ON m.id=cm.member_id
                   WHERE cm.crew_id=? ORDER BY cm.position,m.name""",
                (crew_id,),
            ).fetchall()
        ]

    def save_crew(self, data: dict[str, Any], crew_id: str | None = None) -> str:
        crew_id = crew_id or new_id("CR")
        name = str(data.get("name") or "").strip()
        members = [
            str(member_id).strip() for member_id in data.get("members", [])
            if str(member_id).strip()
        ]
        members = list(dict.fromkeys(members))
        if not name:
            raise ValueError("Crew name is required.")
        if not members:
            raise ValueError("Select at least one crew member.")
        now = now_iso()
        values = (name, "", as_bool(data.get("active", True)), now)
        with self.connect() as conn:
            placeholders = ",".join("?" for _ in members)
            valid_member_ids = {
                row["id"]
                for row in conn.execute(
                    f"SELECT id FROM team_members WHERE id IN ({placeholders})",
                    members,
                ).fetchall()
            }
            missing = [member_id for member_id in members if member_id not in valid_member_ids]
            if missing:
                raise ValueError("One or more selected team members no longer exist.")
            conflicts = [
                row["name"]
                for row in conn.execute(
                    f"""SELECT DISTINCT c.name FROM crew_memberships cm
                        JOIN team_crews c ON c.id=cm.crew_id
                        WHERE cm.member_id IN ({placeholders}) AND cm.crew_id!=?""",
                    (*members, crew_id),
                ).fetchall()
            ]
            if conflicts:
                raise ValueError(
                    "A person can only be in one crew. Remove the selected person from: "
                    + ", ".join(conflicts)
                )
            if conn.execute("SELECT 1 FROM team_crews WHERE id=?", (crew_id,)).fetchone():
                conn.execute(
                    "UPDATE team_crews SET name=?,members=?,active=?,updated_at=? WHERE id=?",
                    (*values, crew_id),
                )
            else:
                conn.execute(
                    "INSERT INTO team_crews VALUES (?,?,?,?,?,?)",
                    (crew_id, *values[:-1], now, now),
                )
            conn.execute("DELETE FROM crew_memberships WHERE crew_id=?", (crew_id,))
            conn.executemany(
                """INSERT INTO crew_memberships (crew_id,member_id,position)
                   VALUES (?,?,?)""",
                [(crew_id, member_id, position) for position, member_id in enumerate(members)],
            )
            technicians = ",".join(
                person["name"] for person in self._crew_people(conn, crew_id)
            )
            conn.execute(
                """UPDATE schedule_assignments
                   SET team_label=?,assigned_technicians=?,updated_at=?
                   WHERE crew_id=? AND status!='Complete'""",
                (name, technicians, now, crew_id),
            )
        return crew_id

    def delete_crew(self, crew_id: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM team_crews WHERE id=?", (crew_id,))

    def list_assets(self, active_only: bool = False) -> list[dict[str, Any]]:
        query = "SELECT * FROM assets"
        if active_only:
            query += " WHERE active=1"
        query += " ORDER BY asset_number"
        with self.connect() as conn:
            return self._dicts(conn.execute(query).fetchall())

    def save_asset(self, data: dict[str, Any], asset_id: str | None = None) -> str:
        asset_id = asset_id or new_id("AS")
        now = now_iso()
        values = (
            str(data.get("asset_number", "")).strip().upper(),
            str(data.get("asset_name", "")).strip(),
            str(data.get("location", "")).strip(),
            str(data.get("department", "Operations")).strip(),
            str(data.get("criticality", "Normal")),
            str(data.get("manufacturer", "")).strip(),
            str(data.get("model", "")).strip(),
            as_bool(data.get("active", True)),
            str(data.get("notes", "")).strip(),
            now,
        )
        if not values[0] or not values[1]:
            raise ValueError("Asset number and asset name are required.")
        with self.connect() as conn:
            if conn.execute("SELECT 1 FROM assets WHERE id=?", (asset_id,)).fetchone():
                conn.execute(
                    """UPDATE assets SET asset_number=?,asset_name=?,location=?,department=?,criticality=?,manufacturer=?,model=?,active=?,notes=?,updated_at=? WHERE id=?""",
                    (*values, asset_id),
                )
            else:
                conn.execute(
                    """INSERT INTO assets (id,asset_number,asset_name,location,department,criticality,manufacturer,model,active,notes,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (asset_id, *values[:-1], now, now),
                )
        return asset_id

    def delete_asset(self, asset_id: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM assets WHERE id=?", (asset_id,))

    def list_jobs(self, status: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM work_orders"
        params: tuple[Any, ...] = ()
        if status and status != "All":
            if status == "Open":
                query += " WHERE status NOT IN ('Completed','Complete')"
            else:
                query += " WHERE status=?"
                params = (status,)
        query += " ORDER BY CASE WHEN status IN ('Completed','Complete') THEN 1 ELSE 0 END, priority_score DESC, due_at"
        with self.connect() as conn:
            return self._dicts(conn.execute(query, params).fetchall())

    def save_job(self, data: dict[str, Any], work_order_id: str | None = None) -> str:
        work_order_id = str(
            work_order_id or data.get("work_order_id") or data.get("id") or ""
        ).strip()
        if not work_order_id:
            raise ValueError("Work order number is required.")
        now = now_iso()
        allowed = data.get("allowed_days") or DAYS[:5]
        if isinstance(allowed, str):
            allowed_days = allowed
        else:
            allowed_days = ",".join(day for day in allowed if day in DAYS)
        flags = [
            as_bool(data.get("weekend_allowed", False)), as_bool(data.get("requires_shutdown", False)),
            as_bool(data.get("fixed_day_job", False)), as_bool(data.get("can_split_across_days", True)),
            as_bool(data.get("scope_ready", True)), as_bool(data.get("parts_ready", True)),
            as_bool(data.get("permits_ready", True)), as_bool(data.get("shutdown_ready", True)),
            as_bool(data.get("ready_to_schedule", True)),
        ]
        values = (
            str(data.get("title", "")).strip(), str(data.get("asset", "UNASSIGNED")),
            str(data.get("location", "Plant")).strip(), str(data.get("due_at", now)),
            str(data.get("priority", "Medium")), str(data.get("status", "Pending")),
            str(data.get("technician", "Unassigned")), max(0.5, float(data.get("duration_hours", 1))),
            str(data.get("category", "Mechanical")), str(data.get("notes", "")),
            str(data.get("department", "Operations")), max(0, int(data.get("mechanical_manpower", 0))),
            max(0, int(data.get("welding_manpower", 0))), max(1, int(data.get("crew_size_required", 1))),
            max(1, min(20, int(data.get("priority_score", 7)))), allowed_days or ",".join(DAYS[:5]),
            str(data.get("preferred_day", "")), str(data.get("earliest_start_day", "")),
            str(data.get("latest_finish_day", "")), *flags, now,
        )
        if not values[0]:
            raise ValueError("Job title is required.")
        with self.connect() as conn:
            if conn.execute("SELECT 1 FROM work_orders WHERE id=?", (work_order_id,)).fetchone():
                conn.execute(
                    """UPDATE work_orders SET title=?,asset=?,location=?,due_at=?,priority=?,status=?,technician=?,duration_hours=?,category=?,notes=?,department=?,mechanical_manpower=?,welding_manpower=?,crew_size_required=?,priority_score=?,allowed_days=?,preferred_day=?,earliest_start_day=?,latest_finish_day=?,weekend_allowed=?,requires_shutdown=?,fixed_day_job=?,can_split_across_days=?,scope_ready=?,parts_ready=?,permits_ready=?,shutdown_ready=?,ready_to_schedule=?,updated_at=? WHERE id=?""",
                    (*values, work_order_id),
                )
            else:
                conn.execute(
                    """INSERT INTO work_orders (id,title,asset,location,due_at,priority,status,technician,duration_hours,category,notes,department,mechanical_manpower,welding_manpower,crew_size_required,priority_score,allowed_days,preferred_day,earliest_start_day,latest_finish_day,weekend_allowed,requires_shutdown,fixed_day_job,can_split_across_days,scope_ready,parts_ready,permits_ready,shutdown_ready,ready_to_schedule,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (work_order_id, *values[:-1], now, now),
                )
            if values[5] in ("Completed", "Complete"):
                conn.execute(
                    """UPDATE work_orders
                       SET status='Completed',completed_at=COALESCE(completed_at,?),updated_at=?
                       WHERE id=?""",
                    (now, now, work_order_id),
                )
        return work_order_id

    def delete_job(self, work_order_id: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM work_orders WHERE id=?", (work_order_id,))

    def delete_all_jobs(self) -> int:
        with self.connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM work_orders").fetchone()[0]
            conn.execute("DELETE FROM schedule_history")
            conn.execute("DELETE FROM schedule_assignments")
            conn.execute("DELETE FROM work_orders")
        return int(count)

    def update_job_status(self, work_order_id: str, status: str) -> None:
        completed = now_iso() if status in ("Completed", "Complete") else None
        with self.connect() as conn:
            conn.execute("UPDATE work_orders SET status=?,completed_at=?,updated_at=? WHERE id=?", (status, completed, now_iso(), work_order_id))

    def list_assignments(self, state: str | None = None, include_complete: bool = True) -> list[dict[str, Any]]:
        where: list[str] = []
        params: list[Any] = []
        if state:
            where.append("a.schedule_state=?")
            params.append(state)
        if not include_complete:
            where.append("a.status!='Complete'")
        query = """SELECT a.*,w.title,w.asset,w.due_at AS work_order_due_at
                   FROM schedule_assignments a
                   LEFT JOIN work_orders w ON w.id=a.work_order_id"""
        if where:
            query += " WHERE " + " AND ".join(where)
        query += " ORDER BY CASE a.day WHEN 'Monday' THEN 1 WHEN 'Tuesday' THEN 2 WHEN 'Wednesday' THEN 3 WHEN 'Thursday' THEN 4 WHEN 'Friday' THEN 5 WHEN 'Saturday' THEN 6 ELSE 7 END,a.team_label,a.priority_score DESC"
        with self.connect() as conn:
            return self._dicts(conn.execute(query, params).fetchall())

    def schedule_warnings(
        self,
        state: str | None = None,
        day_hours_limit: float = 8,
    ) -> list[str]:
        """Return non-blocking warnings without changing the user's crews or plan."""
        rows = self.list_assignments(state, include_complete=False)
        warnings: list[str] = []
        daily_load: dict[tuple[str, str], float] = {}
        intervals: dict[tuple[str, str], list[tuple[datetime, datetime, str]]] = {}
        crew_map = {crew["id"]: crew for crew in self.list_crews()}
        members = {member["id"]: member for member in self.list_team()}
        for row in rows:
            work_date = str(row.get("scheduled_date") or "")
            crew_key = str(row.get("crew_id") or row["team_label"])
            load_key = (work_date, crew_key)
            daily_load[load_key] = daily_load.get(load_key, 0) + float(row["assigned_hours"])
            if work_date and row.get("work_order_due_at"):
                if self._date_value(row["work_order_due_at"]) < self._date_value(work_date):
                    warnings.append(
                        f"{row['work_order_id']} is scheduled for {work_date}, after its due date "
                        f"{str(row['work_order_due_at'])[:10]}."
                    )
            crew = crew_map.get(row.get("crew_id"))
            if crew:
                unavailable = [
                    members[member_id]["name"]
                    for member_id in crew["members"].split(",")
                    if member_id in members
                    and (
                        not members[member_id]["active"]
                        or members[member_id]["availability"] == "Unavailable"
                    )
                ]
                if unavailable:
                    warnings.append(
                        f"{row['work_order_id']} uses {row['team_label']} with unavailable/inactive "
                        f"member(s): {', '.join(unavailable)}."
                    )
            else:
                warnings.append(
                    f"{row['work_order_id']} is assigned to a crew that no longer exists; "
                    "move it to Draft and select a saved crew."
                )
            try:
                start = datetime.fromisoformat(str(row.get("start_at") or ""))
                end = datetime.fromisoformat(str(row.get("end_at") or ""))
                intervals.setdefault(load_key, []).append(
                    (start, end, str(row["work_order_id"]))
                )
                if end.date() != start.date():
                    warnings.append(
                        f"{row['work_order_id']} runs past midnight ({row['start_at']} to {row['end_at']})."
                    )
            except ValueError:
                warnings.append(f"{row['work_order_id']} has an invalid start or end time.")

        for (work_date, crew_key), hours in daily_load.items():
            if hours > day_hours_limit:
                crew_name = crew_map.get(crew_key, {}).get("name", crew_key)
                warnings.append(
                    f"{crew_name} has {hours:.1f}h on {work_date or 'an undated day'}, "
                    f"above the {day_hours_limit:.1f}h planning limit."
                )
        for interval_rows in intervals.values():
            ordered = sorted(interval_rows)
            for previous, current in zip(ordered, ordered[1:]):
                if current[0] < previous[1]:
                    warnings.append(
                        f"{previous[2]} and {current[2]} overlap for the same crew."
                    )
        return list(dict.fromkeys(warnings))

    def _history(self, conn: sqlite3.Connection, assignment_id: str, action: str, old: str = "", new: str = "") -> None:
        conn.execute(
            "INSERT INTO schedule_history VALUES (?,?,?,?,?,?)",
            (new_id("SH"), assignment_id, action, old, new, now_iso()),
        )

    @staticmethod
    def _date_value(value: Any, fallback: date | None = None) -> date:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        try:
            return date.fromisoformat(str(value)[:10])
        except (TypeError, ValueError):
            return fallback or date.today()

    @classmethod
    def _time_values(
        cls,
        day: str,
        hours: float,
        scheduled_date: Any = None,
        start_at: Any = None,
        week_start: Any = None,
        load_hours: float = 0,
    ) -> tuple[str, str, str]:
        if scheduled_date:
            work_date = cls._date_value(scheduled_date)
        else:
            anchor = cls._date_value(week_start)
            monday = anchor - timedelta(days=anchor.weekday())
            work_date = monday + timedelta(days=DAYS.index(day) if day in DAYS else 0)

        start_value: datetime | None = None
        if isinstance(start_at, datetime):
            start_value = start_at.replace(tzinfo=None)
        elif isinstance(start_at, time):
            start_value = datetime.combine(work_date, start_at)
        elif start_at:
            raw = str(start_at).strip()
            try:
                start_value = datetime.fromisoformat(raw).replace(tzinfo=None)
            except ValueError:
                try:
                    start_value = datetime.combine(work_date, time.fromisoformat(raw))
                except ValueError:
                    start_value = None
        if start_value is None:
            start_value = datetime.combine(work_date, time(8)) + timedelta(hours=load_hours)
        elif start_value.date() != work_date:
            start_value = datetime.combine(work_date, start_value.time())
        end_value = start_value + timedelta(hours=max(0.5, float(hours)))
        return (
            work_date.isoformat(),
            start_value.isoformat(timespec="minutes"),
            end_value.isoformat(timespec="minutes"),
        )

    def generate_draft(
        self,
        day_hours_limit: float = 8,
        clear_existing: bool = True,
        week_start: Any = None,
    ) -> dict[str, Any]:
        """Build a draft using only the exact active crews saved by the user."""
        anchor = self._date_value(week_start)
        week_monday = anchor - timedelta(days=anchor.weekday())
        with self.connect() as conn:
            if clear_existing:
                conn.execute(
                    "DELETE FROM schedule_assignments WHERE schedule_state='Draft' AND status!='Complete'"
                )
                conn.execute("UPDATE work_orders SET status='Pending' WHERE status='Draft Scheduled'")
            jobs = self._dicts(conn.execute("SELECT * FROM work_orders WHERE status NOT IN ('Completed','Complete') AND ready_to_schedule=1 ORDER BY priority_score DESC,due_at").fetchall())
            crews: list[dict[str, Any]] = []
            for row in conn.execute("SELECT * FROM team_crews WHERE active=1 ORDER BY name").fetchall():
                people = self._crew_people(conn, row["id"])
                if people:
                    crews.append({"id": row["id"], "name": row["name"], "people": people})
            if not crews:
                return {
                    "created": 0,
                    "warnings": ["Create at least one active crew in Team > Crews before generating the draft schedule."],
                }
            existing = self._dicts(conn.execute("SELECT * FROM schedule_assignments WHERE status!='Complete'").fetchall())
            daily_crew_load: dict[tuple[str, str], float] = {}
            crew_load: dict[str, float] = {}
            for row in existing:
                crew_key = str(row.get("crew_id") or row["team_label"])
                work_date = str(row.get("scheduled_date") or "")
                if not work_date:
                    work_date = self._time_values(
                        row["day"], float(row["assigned_hours"]), week_start=week_monday
                    )[0]
                assigned_hours = float(row["assigned_hours"])
                daily_crew_load[(work_date, crew_key)] = daily_crew_load.get((work_date, crew_key), 0) + assigned_hours
                crew_load[crew_key] = crew_load.get(crew_key, 0) + assigned_hours
            created = 0
            warnings: list[str] = []
            now = now_iso()
            for job in jobs:
                scheduled = conn.execute("SELECT COALESCE(SUM(assigned_hours),0) FROM schedule_assignments WHERE work_order_id=? AND status!='Complete'", (job["id"],)).fetchone()[0]
                remaining = max(0.0, float(job["duration_hours"]) - float(scheduled))
                if remaining <= 0:
                    continue
                allowed = [day for day in str(job["allowed_days"]).split(",") if day in DAYS]
                if job["preferred_day"] in allowed:
                    allowed = [job["preferred_day"], *[day for day in allowed if day != job["preferred_day"]]]
                if not job["weekend_allowed"]:
                    allowed = [day for day in allowed if day not in ("Saturday", "Sunday")]
                crew_size = max(int(job["crew_size_required"]), int(job["mechanical_manpower"]) + int(job["welding_manpower"]), 1)
                if allowed:
                    choices: list[tuple[tuple[Any, ...], str, str, dict[str, Any]]] = []
                    for day_position, day in enumerate(allowed):
                        work_date = (week_monday + timedelta(days=DAYS.index(day))).isoformat()
                        for crew in crews:
                            choices.append((
                                (
                                    daily_crew_load.get((work_date, crew["id"]), 0),
                                    crew_load.get(crew["id"], 0),
                                    day_position,
                                    crew["name"],
                                ),
                                day,
                                work_date,
                                crew,
                            ))
                    _, day, work_date, selected_crew = min(
                        choices, key=lambda choice: choice[0]
                    )
                    names = [person["name"] for person in selected_crew["people"]]
                    hours = remaining
                    previous_load = daily_crew_load.get((work_date, selected_crew["id"]), 0)
                    scheduled_date, start_at, end_at = self._time_values(
                        day,
                        hours,
                        scheduled_date=work_date,
                        load_hours=previous_load,
                    )
                    assignment_id = new_id("SA")
                    conn.execute(
                        """INSERT INTO schedule_assignments
                           (id,work_order_id,schedule_state,day,team_label,assigned_technicians,
                            assigned_hours,required_crew_size,mechanical_manpower,welding_manpower,
                            priority,priority_score,location,department,notes,status,created_at,updated_at,
                            crew_id,scheduled_date,start_at,end_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            assignment_id, job["id"], "Draft", day, selected_crew["name"], ",".join(names),
                            hours, crew_size, job["mechanical_manpower"], job["welding_manpower"],
                            job["priority"], job["priority_score"], job["location"], job["department"],
                            job["notes"], "Scheduled", now, now, selected_crew["id"],
                            scheduled_date, start_at, end_at,
                        ),
                    )
                    self._history(conn, assignment_id, "Generated", "", f"Draft - {selected_crew['name']}")
                    daily_crew_load[(work_date, selected_crew["id"])] = previous_load + hours
                    crew_load[selected_crew["id"]] = crew_load.get(selected_crew["id"], 0) + hours
                    unavailable = [
                        person["name"] for person in selected_crew["people"]
                        if not person["active"] or person["availability"] == "Unavailable"
                    ]
                    if unavailable:
                        warnings.append(
                            f"{job['id']} uses {selected_crew['name']} with unavailable/inactive "
                            f"member(s): {', '.join(unavailable)}."
                        )
                    if previous_load + hours > day_hours_limit:
                        warnings.append(
                            f"{selected_crew['name']} has {previous_load + hours:.1f}h on "
                            f"{scheduled_date}, above the {day_hours_limit:.1f}h planning limit."
                        )
                    try:
                        if self._date_value(job["due_at"]) < self._date_value(scheduled_date):
                            warnings.append(
                                f"{job['id']} is scheduled for {scheduled_date}, after its due date "
                                f"{str(job['due_at'])[:10]}."
                            )
                    except (TypeError, ValueError):
                        pass
                    remaining = 0
                    created += 1
                if remaining < float(job["duration_hours"]):
                    conn.execute("UPDATE work_orders SET status='Draft Scheduled',updated_at=? WHERE id=?", (now, job["id"]))
                if remaining > 0.01:
                    warnings.append(f"{job['id']} - {job['title']} could not be assigned because it has no allowed scheduling day.")
            return {"created": created, "warnings": warnings}

    def save_manual_assignment(self, data: dict[str, Any]) -> str:
        assignment_ids = self.save_manual_assignments(data)
        return assignment_ids[0]

    def save_manual_assignments(self, data: dict[str, Any]) -> list[str]:
        """Create one assignment row per selected crew for the same work order."""
        raw_labels = data.get("team_labels")
        if raw_labels is None:
            raw_labels = [data.get("team_label")]
        crew_names = list(dict.fromkeys(
            str(label or "").strip() for label in raw_labels
            if str(label or "").strip()
        ))
        if not crew_names:
            raise ValueError("Select at least one active saved crew.")

        with self.connect() as conn:
            job = conn.execute("SELECT * FROM work_orders WHERE id=?", (data["work_order_id"],)).fetchone()
            if not job:
                raise ValueError("Work order not found.")
            selected_crews: list[tuple[dict[str, Any], list[str]]] = []
            for crew_name in crew_names:
                crew = conn.execute(
                    "SELECT * FROM team_crews WHERE name=? AND active=1",
                    (crew_name,),
                ).fetchone()
                if not crew:
                    raise ValueError(f"{crew_name} is not an active saved crew.")
                technicians = [
                    person["name"] for person in self._crew_people(conn, crew["id"])
                ]
                if not technicians:
                    raise ValueError(f"{crew_name} has no members.")
                selected_crews.append((dict(crew), technicians))

            now = now_iso()
            hours = max(0.5, float(data.get("assigned_hours", 1)))
            day = str(data.get("day", job["preferred_day"] or "Monday"))
            scheduled_date, start_at, end_at = self._time_values(
                day,
                hours,
                scheduled_date=data.get("scheduled_date"),
                start_at=data.get("start_at"),
                week_start=data.get("week_start"),
            )
            day = self._date_value(scheduled_date).strftime("%A")
            assignment_ids: list[str] = []
            for crew, technicians in selected_crews:
                assignment_id = new_id("SA")
                conn.execute(
                    """INSERT INTO schedule_assignments
                       (id,work_order_id,schedule_state,day,team_label,assigned_technicians,
                        assigned_hours,required_crew_size,mechanical_manpower,welding_manpower,
                        priority,priority_score,location,department,notes,status,created_at,updated_at,
                        crew_id,scheduled_date,start_at,end_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        assignment_id, job["id"], "Draft", day, crew["name"],
                        ",".join(technicians), hours, job["crew_size_required"],
                        job["mechanical_manpower"], job["welding_manpower"],
                        job["priority"], job["priority_score"], job["location"],
                        job["department"], data.get("notes", job["notes"]),
                        "Scheduled", now, now, crew["id"], scheduled_date, start_at, end_at,
                    ),
                )
                self._history(
                    conn,
                    assignment_id,
                    "Manual assignment",
                    "",
                    f"Draft - {crew['name']}",
                )
                assignment_ids.append(assignment_id)
            conn.execute("UPDATE work_orders SET status='Draft Scheduled',updated_at=? WHERE id=?", (now, job["id"]))
            return assignment_ids

    def update_assignment(self, assignment_id: str, data: dict[str, Any]) -> None:
        with self.connect() as conn:
            old = conn.execute("SELECT * FROM schedule_assignments WHERE id=?", (assignment_id,)).fetchone()
            if not old:
                raise ValueError("Assignment not found.")
            crew_name = str(data.get("team_label", old["team_label"])).strip()
            technicians = old["assigned_technicians"]
            crew_id = old.get("crew_id")
            if crew_name != old["team_label"] or data.get("refresh_crew"):
                crew = conn.execute("SELECT * FROM team_crews WHERE name=? AND active=1", (crew_name,)).fetchone()
                if not crew:
                    raise ValueError("Select an active saved crew.")
                crew_id = crew["id"]
                technicians = ",".join(
                    person["name"] for person in self._crew_people(conn, crew_id)
                )
            hours = max(0.5, float(data.get("assigned_hours", old["assigned_hours"])))
            day = str(data.get("day", old["day"]))
            supplied_date = data.get("scheduled_date")
            week_anchor = old.get("scheduled_date") or date.today()
            if not supplied_date and day == old["day"]:
                supplied_date = old.get("scheduled_date")
            scheduled_date, start_at, end_at = self._time_values(
                day,
                hours,
                scheduled_date=supplied_date,
                start_at=data.get("start_at", old.get("start_at")),
                week_start=week_anchor,
            )
            day = self._date_value(scheduled_date).strftime("%A")
            requested_status = str(data.get("status", old["status"]))
            conn.execute(
                """UPDATE schedule_assignments
                   SET day=?,team_label=?,assigned_technicians=?,assigned_hours=?,status=?,notes=?,
                       updated_at=?,crew_id=?,scheduled_date=?,start_at=?,end_at=?
                   WHERE id=?""",
                (
                    day, crew_name, technicians, hours, requested_status,
                    data.get("notes", old["notes"]), now_iso(), crew_id,
                    scheduled_date, start_at, end_at, assignment_id,
                ),
            )
            self._history(conn, assignment_id, "Updated", str(dict(old)), str(data))
            updated = conn.execute(
                "SELECT * FROM schedule_assignments WHERE id=?", (assignment_id,)
            ).fetchone()
            if requested_status == "Complete":
                self._complete_assignment(conn, updated, previous_status=old["status"])
            else:
                self._sync_work_order(conn, old["work_order_id"])

    def delete_assignment(self, assignment_id: str) -> None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM schedule_assignments WHERE id=?", (assignment_id,)).fetchone()
            if row:
                self._history(conn, assignment_id, "Deleted", str(dict(row)), "")
                conn.execute("DELETE FROM schedule_assignments WHERE id=?", (assignment_id,))
                self._sync_work_order(conn, row["work_order_id"])

    def promote_all(self) -> int:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT id,work_order_id FROM schedule_assignments
                   WHERE schedule_state='Draft' AND status!='Complete'"""
            ).fetchall()
            now = now_iso()
            conn.execute(
                """UPDATE schedule_assignments SET schedule_state='Final',updated_at=?
                   WHERE schedule_state='Draft' AND status!='Complete'""",
                (now,),
            )
            for row in rows:
                self._sync_work_order(conn, row["work_order_id"])
                self._history(conn, row["id"], "Promoted", "Draft", "Final")
            return len(rows)

    def _complete_assignment(
        self,
        conn: ConnectionAdapter,
        row: dict[str, Any],
        previous_status: str | None = None,
    ) -> None:
        now = now_iso()
        original_status = previous_status or row["status"]
        if original_status != "Complete":
            conn.execute(
                "UPDATE schedule_assignments SET status='Complete',updated_at=? WHERE id=?",
                (now, row["id"]),
            )
            self._history(conn, row["id"], "Completed", original_status, "Complete")
        self._sync_work_order(conn, row["work_order_id"])

    def _sync_work_order(self, conn: ConnectionAdapter, work_order_id: str) -> None:
        assignments = conn.execute(
            """SELECT schedule_state,status FROM schedule_assignments
               WHERE work_order_id=?""",
            (work_order_id,),
        ).fetchall()
        now = now_iso()
        incomplete = [row for row in assignments if row["status"] != "Complete"]
        if assignments and not incomplete:
            conn.execute(
                """UPDATE work_orders SET status='Completed',
                   completed_at=COALESCE(completed_at,?),updated_at=? WHERE id=?""",
                (now, now, work_order_id),
            )
            return
        if any(row["schedule_state"] == "Final" for row in incomplete):
            status = "Final Scheduled"
        elif incomplete:
            status = "Draft Scheduled"
        else:
            status = "Pending"
        conn.execute(
            """UPDATE work_orders SET status=?,completed_at=NULL,updated_at=? WHERE id=?""",
            (status, now, work_order_id),
        )

    def complete_assignment(self, assignment_id: str) -> None:
        """Complete one assignment and its work order atomically when all work is done."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM schedule_assignments WHERE id=?", (assignment_id,)
            ).fetchone()
            if not row:
                raise ValueError("Assignment not found.")
            self._complete_assignment(conn, row)

    def change_assignment_state(self, assignment_id: str, state: str) -> None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM schedule_assignments WHERE id=?", (assignment_id,)).fetchone()
            if not row:
                return
            now = now_iso()
            if state == "Complete":
                self._complete_assignment(conn, row)
            else:
                conn.execute("UPDATE schedule_assignments SET schedule_state=?,status='Scheduled',updated_at=? WHERE id=?", (state, now, assignment_id))
                self._sync_work_order(conn, row["work_order_id"])
                self._history(conn, assignment_id, "State changed", row["schedule_state"], state)

    def reset_schedule(self, state: str) -> int:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT id,work_order_id FROM schedule_assignments
                   WHERE schedule_state=? AND status!='Complete'""",
                (state,),
            ).fetchall()
            conn.execute(
                """DELETE FROM schedule_assignments
                   WHERE schedule_state=? AND status!='Complete'""",
                (state,),
            )
            for work_order_id in {row["work_order_id"] for row in rows}:
                self._sync_work_order(conn, work_order_id)
            count = len(rows)
            return int(count)

    def clear_final_schedule(self) -> int:
        """Remove unfinished Final assignments while preserving completed work."""
        with self.connect() as conn:
            assignments = conn.execute(
                """SELECT id,work_order_id
                   FROM schedule_assignments
                   WHERE schedule_state='Final' AND status!='Complete'"""
            ).fetchall()
            if not assignments:
                return 0

            stamp = now_iso()
            affected_work_orders = {row["work_order_id"] for row in assignments}
            for row in assignments:
                self._history(conn, row["id"], "Cleared", "Final", "Pending")
                conn.execute("DELETE FROM schedule_assignments WHERE id=?", (row["id"],))

            for work_order_id in affected_work_orders:
                remaining = conn.execute(
                    """SELECT COUNT(*) FROM schedule_assignments
                       WHERE work_order_id=? AND status!='Complete'""",
                    (work_order_id,),
                ).fetchone()[0]
                if remaining == 0:
                    conn.execute(
                        """UPDATE work_orders
                           SET status='Pending',completed_at=NULL,updated_at=?
                           WHERE id=? AND status='Final Scheduled'""",
                        (stamp, work_order_id),
                    )
            return len(assignments)

    def reopen_job(self, work_order_id: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE work_orders SET status='Pending',completed_at=NULL,updated_at=? WHERE id=?", (now_iso(), work_order_id))

    def list_history(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return self._dicts(conn.execute("SELECT * FROM schedule_history ORDER BY changed_at DESC LIMIT ?", (limit,)).fetchall())

    def jobs_csv(self) -> bytes:
        rows = self.list_jobs("All")
        if not rows:
            return b""
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
        return buffer.getvalue().encode("utf-8")

    def import_jobs_csv(self, payload: bytes) -> dict[str, int]:
        reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")))
        return self.import_jobs_records(reader)

    def import_jobs_records(
        self,
        rows: Iterable[dict[str, Any]],
    ) -> dict[str, int]:
        """Import incomplete spreadsheet rows using safe temporary defaults."""
        created = 0
        updated = 0
        existing_ids = {job["id"] for job in self.list_jobs("All")}
        seen_upload_ids: set[str] = set()

        def clean(value: Any) -> str:
            result = str(value if value is not None else "").strip()
            return "" if result.lower() in ("nan", "nat", "none", "<na>") else result

        def text(row: dict[str, Any], *keys: str, default: str = "") -> str:
            for key in keys:
                value = clean(row.get(key))
                if value:
                    return value
            return default

        def number(value: Any, default: float) -> float:
            try:
                result = float(value)
                return result if math.isfinite(result) else default
            except (TypeError, ValueError):
                return default

        for position, row in enumerate(rows, start=1):
            normalized_row = {
                clean(key).lower().replace(" ", "_"): value
                for key, value in row.items()
                if clean(key)
            }
            row = normalized_row
            if not any(clean(value) for value in row.values()):
                continue
            job_id = text(
                row, "id", "work_order_number", "work_order", "work_order_id",
                "work_order_no", "wo", "wo_number",
            ) or new_id("IMPORT")
            base_id = job_id
            duplicate_number = 2
            while job_id in seen_upload_ids:
                job_id = f"{base_id}-{duplicate_number}"
                duplicate_number += 1
            seen_upload_ids.add(job_id)
            existing = job_id in existing_ids

            data: dict[str, Any] = dict(row)
            data["title"] = text(
                row, "title", "job", "job_name", "job_description",
                "work_description", "description", "task",
                default=f"Imported job {position}",
            )
            data["asset"] = text(
                row, "asset", "asset_number", "equipment", "equipment_number",
                default="UNASSIGNED",
            )
            data["location"] = text(row, "location", "site", "area", default="Plant")
            data["department"] = text(row, "department", default="Operations")
            data["due_at"] = text(
                row, "due_at", "due", "due_date", "date_due",
                default=now_iso(),
            )
            data["duration_hours"] = max(
                .5,
                number(
                    row.get("duration_hours")
                    or row.get("duration")
                    or row.get("estimated_hours"),
                    1,
                ),
            )
            data["priority"] = text(row, "priority", default="Medium")
            data["status"] = text(row, "status", default="Pending")
            data["category"] = text(row, "category", default="General")
            data["notes"] = text(row, "notes", default="")
            data["allowed_days"] = text(
                row, "allowed_days",
                default="Monday,Tuesday,Wednesday,Thursday,Friday",
            )
            data["crew_size_required"] = max(
                1,
                int(number(
                    row.get("crew_size_required") or row.get("crew_size") or row.get("crew"),
                    1,
                )),
            )
            data["mechanical_manpower"] = max(
                0,
                int(number(row.get("mechanical_manpower") or row.get("mechanical"), 0)),
            )
            data["welding_manpower"] = max(
                0,
                int(number(row.get("welding_manpower") or row.get("welding"), 0)),
            )
            data["priority_score"] = max(
                1,
                min(20, int(number(row.get("priority_score") or row.get("score"), 7))),
            )
            for key in ("weekend_allowed", "requires_shutdown", "fixed_day_job", "can_split_across_days", "scope_ready", "parts_ready", "permits_ready", "shutdown_ready", "ready_to_schedule"):
                value = clean(row.get(key, "1")).lower()
                data[key] = value not in ("0", "false", "no", "off", "")
            self.save_job(data, job_id)
            if existing:
                updated += 1
            else:
                created += 1
                existing_ids.add(job_id)
        return {"created": created, "updated": updated}
