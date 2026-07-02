# PlanPilot – Product Architecture

Version: 1.0
Status: Architecture Definition

---

## Product Overview

PlanPilot is a cloud-native SaaS platform for workforce planning and planned absence management.

The platform replaces Excel spreadsheets, emails and manual decision-making with a transparent, rule-based planning system.

The primary goal is to help leaders make faster, fairer and more informed planning decisions while keeping employees engaged through a simple self-service experience.

Version 1 focuses on planned absence, especially vacation planning, but the architecture is designed to evolve into a complete workforce planning platform.

---

## Core Principles

1. **Transparent rules over hidden judgment.** Every approval, denial, or conflict is explained by an explicit, inspectable rule (e.g. coverage minimums, blackout periods, seniority order) rather than an unexplained manager decision.
2. **Self-service first.** Employees can request, view, and adjust their own planned absence without going through email or spreadsheets; leaders intervene only on exceptions and conflicts.
3. **Fairness by design.** Rules that affect who gets priority (first-come-first-served, seniority, rotation) are configurable per team and applied consistently, not case-by-case.
4. **Fast decisions.** Leaders should be able to resolve a request or conflict in seconds, with the relevant context (team coverage, other pending requests) visible in one place.
5. **Evolvable data model.** Version 1 models a single absence type (vacation), but the domain model (people, teams, time periods, requests, rules) is generic enough to extend to shift planning, sick leave, and other workforce planning needs without a rewrite.

---

## User Roles

- **Employee** – submits planned absence requests, views team calendar and their own balance/history, receives status updates.
- **Team Leader / Manager** – reviews and approves/denies requests, sees team coverage and conflicts, configures team-level rules.
- **Admin** – manages organization structure (teams, members), global policies (blackout periods, absence types), and integrations.

---

## Core Domain Model (v1)

| Entity | Key Attributes | Notes |
|---|---|---|
| `Organization` | id, name | Tenant boundary for multi-tenant SaaS. |
| `Team` | id, org_id, name, leader_id | Unit of coverage planning. |
| `User` | id, org_id, team_id, name, email, role | Role ∈ {employee, leader, admin}. |
| `AbsenceType` | id, name (e.g. Vacation), requires_approval | Extensible for future absence types. |
| `AbsenceRequest` | id, user_id, absence_type_id, start_date, end_date, status, created_at | Status ∈ {pending, approved, denied, cancelled}. |
| `Rule` | id, team_id, type, config (JSON) | e.g. min_coverage_pct, blackout_period, max_concurrent_absences. |
| `AuditLogEntry` | id, entity, action, actor_id, timestamp | Supports the "transparent rules" principle. |

---

## Key Workflows

1. **Request** – Employee selects a date range and absence type; the system evaluates applicable rules in real time and shows likely outcome (auto-approve / needs review / conflict) before submission.
2. **Review** – Leader sees pending requests ranked by rule-driven priority, with team coverage visualized for the requested period; approves, denies, or asks for changes.
3. **Conflict resolution** – When multiple requests would breach a coverage rule, the system flags the conflict and surfaces the configured tie-breaker (seniority, first-come-first-served, rotation) as a recommendation, not an automatic override.
4. **Visibility** – All team members can see approved absence on a shared calendar to enable peer coordination without needing manager mediation.

---

## System Architecture (v1)

- **Frontend:** Streamlit app (`streamlit_app.py`) as the initial self-service UI for demo/MVP purposes; expected to be replaced by a dedicated web frontend as the product matures.
- **Backend/data:** Start with a single relational database (tenant-scoped tables per the domain model above); rule evaluation implemented as a pure function/service so it can be unit-tested independently of the UI.
- **Rule engine:** Rules are stored as structured config (not code) so admins can adjust them without deployments; evaluated server-side at request-time and re-evaluated on any change to competing requests.
- **Multi-tenancy:** All data scoped by `org_id` from day one, even though v1 may ship to a single organization, to avoid a costly migration later.

---

## Non-Functional Requirements

- **Auditability:** every state change to a request is logged with actor and reason.
- **Fairness/consistency:** identical inputs to a rule must always produce identical outcomes.
- **Low latency:** rule evaluation and coverage visualization should feel instant (sub-second) in the request flow.

---

## Roadmap Beyond v1

- Additional absence types (sick leave, parental leave, unpaid leave).
- Shift/schedule planning, not just absence.
- Notifications (email/Slack) for status changes and pending reviews.
- Reporting/analytics on coverage and absence trends.

---

_This document was drafted from the original Product Overview; review and adjust principles, roles, and the domain model to match actual product decisions before treating this as final._
