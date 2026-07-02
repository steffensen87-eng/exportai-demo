from datetime import date, datetime

from planpilot.models import AbsenceRequest, RequestStatus, Role, Rule, RuleOutcome, User
from planpilot.rules import evaluate_request

TEAM_ID = 1


def make_team(size: int) -> list[User]:
    return [
        User(id=i, org_id=1, team_id=TEAM_ID, name=f"User {i}", email=f"user{i}@example.com", role=Role.EMPLOYEE)
        for i in range(1, size + 1)
    ]


def make_approved(user_id: int, start: date, end: date) -> AbsenceRequest:
    return AbsenceRequest(
        id=0,
        user_id=user_id,
        absence_type_id=1,
        start_date=start,
        end_date=end,
        status=RequestStatus.APPROVED,
        created_at=datetime.now(),
    )


class Candidate:
    def __init__(self, user_id: int, start: date, end: date):
        self.user_id = user_id
        self.start_date = start
        self.end_date = end


def coverage_rule(min_pct: float) -> Rule:
    return Rule(id=1, team_id=TEAM_ID, type="min_coverage", config={"min_coverage_pct": min_pct})


def max_concurrent_rule(max_concurrent: int) -> Rule:
    return Rule(id=2, team_id=TEAM_ID, type="max_concurrent_absences", config={"max_concurrent": max_concurrent})


def blackout_rule(start: date, end: date, label: str) -> Rule:
    return Rule(id=3, team_id=TEAM_ID, type="blackout_period", config={"start": start, "end": end, "label": label})


def test_auto_approves_when_no_conflicts():
    team = make_team(5)
    candidate = Candidate(user_id=1, start=date(2026, 8, 3), end=date(2026, 8, 5))
    rules = [coverage_rule(0.6), max_concurrent_rule(2)]

    result = evaluate_request(candidate, team, approved_requests=[], rules=rules)

    assert result.outcome == RuleOutcome.AUTO_APPROVED


def test_flags_coverage_breach_for_review():
    team = make_team(5)
    approved = [
        make_approved(2, date(2026, 8, 3), date(2026, 8, 5)),
        make_approved(3, date(2026, 8, 3), date(2026, 8, 5)),
    ]
    candidate = Candidate(user_id=1, start=date(2026, 8, 3), end=date(2026, 8, 5))
    rules = [coverage_rule(0.6)]  # 3 absent / 5 -> coverage 0.4 < 0.6

    result = evaluate_request(candidate, team, approved_requests=approved, rules=rules)

    assert result.outcome == RuleOutcome.NEEDS_REVIEW
    assert any("coverage" in reason.lower() for reason in result.reasons)


def test_blocks_when_exceeding_max_concurrent():
    team = make_team(5)
    approved = [
        make_approved(2, date(2026, 8, 3), date(2026, 8, 5)),
        make_approved(3, date(2026, 8, 3), date(2026, 8, 5)),
    ]
    candidate = Candidate(user_id=1, start=date(2026, 8, 3), end=date(2026, 8, 5))
    rules = [max_concurrent_rule(2)]  # candidate would make it 3

    result = evaluate_request(candidate, team, approved_requests=approved, rules=rules)

    assert result.outcome == RuleOutcome.BLOCKED
    assert any("concurrent" in reason.lower() for reason in result.reasons)


def test_flags_blackout_period_for_review():
    team = make_team(5)
    candidate = Candidate(user_id=1, start=date(2026, 12, 22), end=date(2026, 12, 26))
    rules = [blackout_rule(date(2026, 12, 20), date(2026, 12, 31), "Year-end freeze")]

    result = evaluate_request(candidate, team, approved_requests=[], rules=rules)

    assert result.outcome == RuleOutcome.NEEDS_REVIEW
    assert any("Year-end freeze" in reason for reason in result.reasons)


def test_blocked_outranks_needs_review():
    team = make_team(5)
    approved = [
        make_approved(2, date(2026, 12, 22), date(2026, 12, 24)),
        make_approved(3, date(2026, 12, 22), date(2026, 12, 24)),
    ]
    candidate = Candidate(user_id=1, start=date(2026, 12, 22), end=date(2026, 12, 24))
    rules = [
        blackout_rule(date(2026, 12, 20), date(2026, 12, 31), "Year-end freeze"),
        max_concurrent_rule(2),
    ]

    result = evaluate_request(candidate, team, approved_requests=approved, rules=rules)

    assert result.outcome == RuleOutcome.BLOCKED
