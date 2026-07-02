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
