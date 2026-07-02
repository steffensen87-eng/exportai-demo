"""Rule engine: evaluates an absence request against team rules.

Rules are data (Rule.config), not code, so admins can tune them without a
deploy. Each rule type is checked for every day in the requested range and
contributes at most one reason to the result.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from planpilot.models import AbsenceRequest, Rule, RuleOutcome, User

RULE_BLACKOUT_PERIOD = "blackout_period"
RULE_MAX_CONCURRENT_ABSENCES = "max_concurrent_absences"
RULE_MIN_COVERAGE = "min_coverage"


@dataclass
class RuleEvaluation:
    outcome: RuleOutcome
    reasons: list[str]


def _dates_in_range(start: date, end: date):
    days = (end - start).days
    for offset in range(days + 1):
        yield start + timedelta(days=offset)


def _overlaps(a_start: date, a_end: date, b_start: date, b_end: date) -> bool:
    return a_start <= b_end and b_start <= a_end


def evaluate_request(
    candidate: AbsenceRequest,
    team_members: list[User],
    approved_requests: list[AbsenceRequest],
    rules: list[Rule],
) -> RuleEvaluation:
    """Evaluate a candidate request. Does not mutate any input."""
    team_size = len(team_members)
    blocked_reasons: list[str] = []
    review_reasons: list[str] = []

    blackout_rules = [r for r in rules if r.type == RULE_BLACKOUT_PERIOD]
    max_concurrent_rules = [r for r in rules if r.type == RULE_MAX_CONCURRENT_ABSENCES]
    coverage_rules = [r for r in rules if r.type == RULE_MIN_COVERAGE]

    flagged_blackout_labels: set[str] = set()
    flagged_max_concurrent = False
    flagged_coverage = False

    for day in _dates_in_range(candidate.start_date, candidate.end_date):
        concurrent_absentees = 1  # the candidate itself
        for req in approved_requests:
            if req.user_id == candidate.user_id:
                continue
            if _overlaps(req.start_date, req.end_date, day, day):
                concurrent_absentees += 1

        for rule in blackout_rules:
            b_start = rule.config["start"]
            b_end = rule.config["end"]
            if b_start <= day <= b_end:
                flagged_blackout_labels.add(rule.config.get("label", "Blackout period"))

        for rule in max_concurrent_rules:
            max_allowed = rule.config["max_concurrent"]
            if concurrent_absentees > max_allowed:
                flagged_max_concurrent = True

        if team_size > 0:
            for rule in coverage_rules:
                min_coverage_pct = rule.config["min_coverage_pct"]
                coverage = (team_size - concurrent_absentees) / team_size
                if coverage < min_coverage_pct:
                    flagged_coverage = True

    for label in sorted(flagged_blackout_labels):
        review_reasons.append(f"Overlaps blackout period: {label}")

    if flagged_max_concurrent:
        blocked_reasons.append("Would exceed the maximum number of concurrent absences for the team")

    if flagged_coverage:
        review_reasons.append("Would drop team coverage below the configured minimum on one or more days")

    if blocked_reasons:
        return RuleEvaluation(outcome=RuleOutcome.BLOCKED, reasons=blocked_reasons + review_reasons)
    if review_reasons:
        return RuleEvaluation(outcome=RuleOutcome.NEEDS_REVIEW, reasons=review_reasons)
    return RuleEvaluation(outcome=RuleOutcome.AUTO_APPROVED, reasons=["No rule conflicts for the requested dates"])
