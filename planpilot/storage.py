"""SQLite-backed storage for PlanPilot v1, seeded with demo data.

Kept intentionally simple (no ORM) since this is a single-tenant MVP; the
schema still carries org_id/team_id on every row so it does not need to be
reshaped when multi-tenancy actually matters.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime

from planpilot.models import (
    AbsenceRequest,
    AbsenceType,
    Role,
    Rule,
    RuleOutcome,
    RequestStatus,
    Team,
    User,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS organizations (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS teams (
    id INTEGER PRIMARY KEY,
    org_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    leader_id INTEGER
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    org_id INTEGER NOT NULL,
    team_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    role TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS absence_types (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    requires_approval INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS absence_requests (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    absence_type_id INTEGER NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    outcome TEXT,
    reasons TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS rules (
    id INTEGER PRIMARY KEY,
    team_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    config TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY,
    entity TEXT NOT NULL,
    action TEXT NOT NULL,
    actor_id INTEGER NOT NULL,
    request_id INTEGER,
    timestamp TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);
"""


class Storage:
    def __init__(self, db_path: str = "planpilot.db"):
        self.db_path = db_path
        self._init_schema()
        self._seed_if_empty()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def _seed_if_empty(self) -> None:
        with self._connect() as conn:
            if conn.execute("SELECT COUNT(*) FROM organizations").fetchone()[0] > 0:
                return

            conn.execute("INSERT INTO organizations (id, name) VALUES (1, 'Northwind Logistics')")
            conn.execute(
                "INSERT INTO teams (id, org_id, name, leader_id) VALUES (1, 1, 'Warehouse Ops', 1)"
            )

            demo_users = [
                (1, "Alice Chen", "alice@northwind.example", Role.LEADER),
                (2, "Bob Ibrahim", "bob@northwind.example", Role.EMPLOYEE),
                (3, "Carol Ng", "carol@northwind.example", Role.EMPLOYEE),
                (4, "Dan Osei", "dan@northwind.example", Role.EMPLOYEE),
                (5, "Eve Lindqvist", "eve@northwind.example", Role.EMPLOYEE),
            ]
            conn.executemany(
                "INSERT INTO users (id, org_id, team_id, name, email, role) VALUES (?, 1, 1, ?, ?, ?)",
                [(uid, name, email, role.value) for uid, name, email, role in demo_users],
            )

            conn.execute(
                "INSERT INTO absence_types (id, name, requires_approval) VALUES (1, 'Vacation', 1)"
            )

            demo_rules = [
                (1, 1, "min_coverage", {"min_coverage_pct": 0.6}),
                (2, 1, "max_concurrent_absences", {"max_concurrent": 2}),
                (
                    3,
                    1,
                    "blackout_period",
                    {"start": "2026-12-20", "end": "2026-12-31", "label": "Year-end freeze"},
                ),
            ]
            conn.executemany(
                "INSERT INTO rules (id, team_id, type, config) VALUES (?, ?, ?, ?)",
                [(rid, team_id, rtype, json.dumps(config)) for rid, team_id, rtype, config in demo_rules],
            )
            conn.commit()

    # -- reads -----------------------------------------------------------

    def get_team(self, team_id: int) -> Team:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM teams WHERE id = ?", (team_id,)).fetchone()
            return Team(id=row["id"], org_id=row["org_id"], name=row["name"], leader_id=row["leader_id"])

    def get_users(self) -> list[User]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM users ORDER BY id").fetchall()
            return [_row_to_user(r) for r in rows]

    def get_user(self, user_id: int) -> User:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            return _row_to_user(row)

    def get_team_members(self, team_id: int) -> list[User]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM users WHERE team_id = ? ORDER BY id", (team_id,)
            ).fetchall()
            return [_row_to_user(r) for r in rows]

    def get_rules(self, team_id: int) -> list[Rule]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM rules WHERE team_id = ?", (team_id,)).fetchall()
            return [
                Rule(id=r["id"], team_id=r["team_id"], type=r["type"], config=_decode_config(r["type"], r["config"]))
                for r in rows
            ]

    def upsert_single_rule(self, team_id: int, rule_type: str, config: dict) -> Rule:
        """Create or update the one rule of `rule_type` for a team (coverage / max-concurrent)."""
        encoded = _encode_config(rule_type, config)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM rules WHERE team_id = ? AND type = ?", (team_id, rule_type)
            ).fetchone()
            if row:
                conn.execute("UPDATE rules SET config = ? WHERE id = ?", (json.dumps(encoded), row["id"]))
                rule_id = row["id"]
            else:
                cur = conn.execute(
                    "INSERT INTO rules (team_id, type, config) VALUES (?, ?, ?)",
                    (team_id, rule_type, json.dumps(encoded)),
                )
                rule_id = cur.lastrowid
            conn.commit()
        return Rule(id=rule_id, team_id=team_id, type=rule_type, config=config)

    def add_blackout_rule(self, team_id: int, start: date, end: date, label: str) -> Rule:
        config = {"start": start.isoformat(), "end": end.isoformat(), "label": label}
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO rules (team_id, type, config) VALUES (?, 'blackout_period', ?)",
                (team_id, json.dumps(config)),
            )
            rule_id = cur.lastrowid
            conn.commit()
        return Rule(id=rule_id, team_id=team_id, type="blackout_period", config={"start": start, "end": end, "label": label})

    def delete_rule(self, rule_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM rules WHERE id = ?", (rule_id,))
            conn.commit()

    def get_absence_types(self) -> list[AbsenceType]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM absence_types ORDER BY id").fetchall()
            return [
                AbsenceType(id=r["id"], name=r["name"], requires_approval=bool(r["requires_approval"]))
                for r in rows
            ]

    def list_requests(
        self,
        team_id: int | None = None,
        user_id: int | None = None,
        status: RequestStatus | None = None,
    ) -> list[AbsenceRequest]:
        query = "SELECT ar.* FROM absence_requests ar JOIN users u ON u.id = ar.user_id WHERE 1=1"
        params: list = []
        if team_id is not None:
            query += " AND u.team_id = ?"
            params.append(team_id)
        if user_id is not None:
            query += " AND ar.user_id = ?"
            params.append(user_id)
        if status is not None:
            query += " AND ar.status = ?"
            params.append(status.value)
        query += " ORDER BY ar.created_at"

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            return [_row_to_request(r) for r in rows]

    # -- writes ------------------------------------------------------------

    def create_request(
        self,
        user_id: int,
        absence_type_id: int,
        start_date: date,
        end_date: date,
        note: str,
        outcome: RuleOutcome,
        reasons: list[str],
    ) -> AbsenceRequest:
        status = RequestStatus.APPROVED if outcome == RuleOutcome.AUTO_APPROVED else RequestStatus.PENDING
        now = datetime.now()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO absence_requests
                    (user_id, absence_type_id, start_date, end_date, status, created_at, note, outcome, reasons)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    absence_type_id,
                    start_date.isoformat(),
                    end_date.isoformat(),
                    status.value,
                    now.isoformat(),
                    note,
                    outcome.value,
                    json.dumps(reasons),
                ),
            )
            request_id = cur.lastrowid
            conn.execute(
                "INSERT INTO audit_log (entity, action, actor_id, request_id, timestamp, detail) VALUES (?, ?, ?, ?, ?, ?)",
                ("AbsenceRequest", f"created:{status.value}", user_id, request_id, now.isoformat(), "; ".join(reasons)),
            )
            conn.commit()
        return self.get_request(request_id)

    def get_request(self, request_id: int) -> AbsenceRequest:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM absence_requests WHERE id = ?", (request_id,)).fetchone()
            return _row_to_request(row)

    def update_request_status(self, request_id: int, status: RequestStatus, actor_id: int) -> None:
        now = datetime.now()
        with self._connect() as conn:
            conn.execute(
                "UPDATE absence_requests SET status = ? WHERE id = ?", (status.value, request_id)
            )
            conn.execute(
                "INSERT INTO audit_log (entity, action, actor_id, request_id, timestamp, detail) VALUES (?, ?, ?, ?, ?, ?)",
                ("AbsenceRequest", f"status_changed:{status.value}", actor_id, request_id, now.isoformat(), ""),
            )
            conn.commit()

    def get_team_activity(self, team_id: int, limit: int = 30) -> list[dict]:
        query = """
            SELECT
                al.action, al.actor_id, al.timestamp, al.detail,
                ar.user_id AS owner_id, ar.start_date, ar.end_date
            FROM audit_log al
            JOIN absence_requests ar ON ar.id = al.request_id
            JOIN users u ON u.id = ar.user_id
            WHERE u.team_id = ?
            ORDER BY al.timestamp DESC
            LIMIT ?
        """
        with self._connect() as conn:
            rows = conn.execute(query, (team_id, limit)).fetchall()
            events = []
            for r in rows:
                actor = self.get_user(r["actor_id"])
                owner = self.get_user(r["owner_id"])
                events.append(
                    {
                        "timestamp": datetime.fromisoformat(r["timestamp"]),
                        "actor_name": actor.name,
                        "owner_name": owner.name,
                        "action": r["action"],
                        "start_date": date.fromisoformat(r["start_date"]),
                        "end_date": date.fromisoformat(r["end_date"]),
                        "detail": r["detail"],
                    }
                )
            return events

    def cancel_request(self, request_id: int, user_id: int) -> None:
        request = self.get_request(request_id)
        if request.user_id != user_id:
            raise PermissionError("Only the requester can cancel their own request")
        if request.status not in (RequestStatus.PENDING, RequestStatus.APPROVED):
            raise ValueError(f"Cannot cancel a request with status '{request.status.value}'")
        self.update_request_status(request_id, RequestStatus.CANCELLED, user_id)


def _decode_config(rule_type: str, raw_config: str) -> dict:
    config = json.loads(raw_config)
    if rule_type == "blackout_period":
        config["start"] = date.fromisoformat(config["start"])
        config["end"] = date.fromisoformat(config["end"])
    return config


def _encode_config(rule_type: str, config: dict) -> dict:
    if rule_type == "blackout_period":
        encoded = dict(config)
        encoded["start"] = config["start"].isoformat() if isinstance(config["start"], date) else config["start"]
        encoded["end"] = config["end"].isoformat() if isinstance(config["end"], date) else config["end"]
        return encoded
    return config


def _row_to_user(row: sqlite3.Row) -> User:
    return User(
        id=row["id"],
        org_id=row["org_id"],
        team_id=row["team_id"],
        name=row["name"],
        email=row["email"],
        role=Role(row["role"]),
    )


def _row_to_request(row: sqlite3.Row) -> AbsenceRequest:
    return AbsenceRequest(
        id=row["id"],
        user_id=row["user_id"],
        absence_type_id=row["absence_type_id"],
        start_date=date.fromisoformat(row["start_date"]),
        end_date=date.fromisoformat(row["end_date"]),
        status=RequestStatus(row["status"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        note=row["note"],
        outcome=RuleOutcome(row["outcome"]) if row["outcome"] else None,
        reasons=json.loads(row["reasons"]),
    )
