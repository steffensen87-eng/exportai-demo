from datetime import date

import pytest

from planpilot.models import RequestStatus, RuleOutcome
from planpilot.storage import Storage


@pytest.fixture
def storage(tmp_path):
    return Storage(db_path=str(tmp_path / "planpilot.db"))


def test_cancel_own_pending_request(storage):
    req = storage.create_request(
        user_id=2,
        absence_type_id=1,
        start_date=date(2026, 12, 22),  # inside seeded blackout -> needs_review -> pending
        end_date=date(2026, 12, 24),
        note="",
        outcome=RuleOutcome.NEEDS_REVIEW,
        reasons=["test"],
    )
    assert req.status == RequestStatus.PENDING

    storage.cancel_request(req.id, user_id=2)

    assert storage.get_request(req.id).status == RequestStatus.CANCELLED


def test_cannot_cancel_someone_elses_request(storage):
    req = storage.create_request(
        user_id=2,
        absence_type_id=1,
        start_date=date(2026, 8, 3),
        end_date=date(2026, 8, 5),
        note="",
        outcome=RuleOutcome.AUTO_APPROVED,
        reasons=["ok"],
    )

    with pytest.raises(PermissionError):
        storage.cancel_request(req.id, user_id=3)


def test_cannot_cancel_already_denied_request(storage):
    req = storage.create_request(
        user_id=2,
        absence_type_id=1,
        start_date=date(2026, 8, 3),
        end_date=date(2026, 8, 5),
        note="",
        outcome=RuleOutcome.NEEDS_REVIEW,
        reasons=["ok"],
    )
    storage.update_request_status(req.id, RequestStatus.DENIED, actor_id=1)

    with pytest.raises(ValueError):
        storage.cancel_request(req.id, user_id=2)


def test_cancelled_request_excluded_from_approved_list(storage):
    req = storage.create_request(
        user_id=2,
        absence_type_id=1,
        start_date=date(2026, 8, 3),
        end_date=date(2026, 8, 5),
        note="",
        outcome=RuleOutcome.AUTO_APPROVED,
        reasons=["ok"],
    )
    assert len(storage.list_requests(status=RequestStatus.APPROVED)) == 1

    storage.cancel_request(req.id, user_id=2)

    assert len(storage.list_requests(status=RequestStatus.APPROVED)) == 0


def test_upsert_single_rule_creates_then_updates(storage):
    rules = storage.get_rules(team_id=1)
    coverage_rule = next(r for r in rules if r.type == "min_coverage")
    assert coverage_rule.config["min_coverage_pct"] == 0.6

    storage.upsert_single_rule(1, "min_coverage", {"min_coverage_pct": 0.8})

    rules = storage.get_rules(team_id=1)
    updated = [r for r in rules if r.type == "min_coverage"]
    assert len(updated) == 1
    assert updated[0].config["min_coverage_pct"] == 0.8


def test_add_and_remove_blackout_rule(storage):
    before = len([r for r in storage.get_rules(team_id=1) if r.type == "blackout_period"])

    new_rule = storage.add_blackout_rule(1, date(2026, 9, 1), date(2026, 9, 5), "Inventory count")
    after_add = [r for r in storage.get_rules(team_id=1) if r.type == "blackout_period"]
    assert len(after_add) == before + 1
    assert any(r.config["label"] == "Inventory count" for r in after_add)

    storage.delete_rule(new_rule.id)
    after_delete = [r for r in storage.get_rules(team_id=1) if r.type == "blackout_period"]
    assert len(after_delete) == before
