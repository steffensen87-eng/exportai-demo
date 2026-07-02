"""Domain model for PlanPilot v1, matching docs/architecture.md."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum


class Role(str, Enum):
    EMPLOYEE = "employee"
    LEADER = "leader"
    ADMIN = "admin"


class RequestStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    CANCELLED = "cancelled"


class RuleOutcome(str, Enum):
    AUTO_APPROVED = "auto_approved"
    NEEDS_REVIEW = "needs_review"
    BLOCKED = "blocked"


@dataclass
class Organization:
    id: int
    name: str


@dataclass
class Team:
    id: int
    org_id: int
    name: str
    leader_id: int | None = None


@dataclass
class User:
    id: int
    org_id: int
    team_id: int
    name: str
    email: str
    role: Role


@dataclass
class AbsenceType:
    id: int
    name: str
    requires_approval: bool = True


@dataclass
class AbsenceRequest:
    id: int
    user_id: int
    absence_type_id: int
    start_date: date
    end_date: date
    status: RequestStatus
    created_at: datetime
    note: str = ""
    outcome: RuleOutcome | None = None
    reasons: list[str] = field(default_factory=list)


@dataclass
class Rule:
    id: int
    team_id: int
    type: str
    config: dict


@dataclass
class AuditLogEntry:
    id: int
    entity: str
    action: str
    actor_id: int
    timestamp: datetime
    detail: str = ""
