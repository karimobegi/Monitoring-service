from sqlmodel import Session, select
from datetime import datetime, timezone, timedelta


from app.models import CheckResult
from app.db import get_endpoint_summary, get_endpoint_incidents, engine
from app.dispatcher import purge_old_results




def test_summary_with_no_checks(endpoint):
    with Session(engine) as session:
        summary = get_endpoint_summary(endpoint.id, session)
    assert summary["total_checks"] == 0
    assert summary["up_checks"] == 0
    assert summary["p50"] is None


def test_summary_counts_up_and_down(endpoint, add_results):
    add_results(200, 200, 500, 200, None)
    with Session(engine) as session:
        summary = get_endpoint_summary(endpoint.id, session)
    assert summary["total_checks"] == 5
    assert summary["up_checks"] == 3          # 500 and None are both down


def test_summary_percentiles_ignore_failures(endpoint, add_results):
    add_results(200, 200, None)
    with Session(engine) as session:
        summary = get_endpoint_summary(endpoint.id, session)
    assert summary["p50"] is not None          # computed from the two successes only


def test_summary_excludes_rows_outside_window(endpoint):
    with Session(engine) as session:
        session.add(CheckResult(
            endpoint_id=endpoint.id,
            checked_at=datetime.now(timezone.utc) - timedelta(days=8),
            status_code=200, error=None, response_time_ms=100,
        ))
        session.commit()
        summary = get_endpoint_summary(endpoint.id, session)
    assert summary["total_checks"] == 0

def test_no_incidents_when_all_up(endpoint, add_results):
    add_results(200, 200, 200)
    with Session(engine) as session:
        assert get_endpoint_incidents(endpoint.id, session) == []


def test_single_down_check_is_one_incident(endpoint, add_results):
    add_results(200, 500, 200)
    with Session(engine) as session:
        incidents = get_endpoint_incidents(endpoint.id, session)
    assert len(incidents) == 1
    assert incidents[0].checks == 1


def test_contiguous_downs_are_one_incident(endpoint, add_results):
    add_results(200, 500, 500, 500, 200)
    with Session(engine) as session:
        incidents = get_endpoint_incidents(endpoint.id, session)
    assert len(incidents) == 1
    assert incidents[0].checks == 3
    assert incidents[0].duration_seconds == 120   # first to last down check


def test_separated_downs_are_two_incidents(endpoint, add_results):
    add_results(500, 200, 500)
    with Session(engine) as session:
        incidents = get_endpoint_incidents(endpoint.id, session)
    assert len(incidents) == 2


def test_null_status_counts_as_down(endpoint, add_results):
    # The bug: NULL BETWEEN 200 AND 399 is NULL, so `NOT is_up` excluded these
    add_results(200, None, None, 200)
    with Session(engine) as session:
        incidents = get_endpoint_incidents(endpoint.id, session)
    assert len(incidents) == 1
    assert incidents[0].checks == 2


def test_ongoing_incident_has_no_recovery(endpoint, add_results):
    add_results(200, 500, 500)
    with Session(engine) as session:
        incidents = get_endpoint_incidents(endpoint.id, session)
    assert len(incidents) == 1
    assert incidents[0].checks == 2

def test_purge_deletes_only_old_rows(endpoint):
    now = datetime.now(timezone.utc)
    with Session(engine) as session:
        for age_days in (45, 31, 29, 1):
            session.add(CheckResult(
                endpoint_id=endpoint.id,
                checked_at=now - timedelta(days=age_days),
                status_code=200, error=None, response_time_ms=100,
            ))
        session.commit()

    purge_old_results()

    with Session(engine) as session:
        remaining = session.exec(select(CheckResult)).all()
    assert len(remaining) == 2          # the 29- and 1-day rows survive


def test_purge_crosses_batch_boundary(endpoint):
    old = datetime.now(timezone.utc) - timedelta(days=45)
    with Session(engine) as session:
        for i in range(5):
            session.add(CheckResult(
                endpoint_id=endpoint.id, checked_at=old + timedelta(seconds=i),
                status_code=200, error=None, response_time_ms=100,
            ))
        session.commit()

    purge_old_results(batch_size=2)     # 2 + 2 + 1, then an empty pass

    with Session(engine) as session:
        assert session.exec(select(CheckResult)).all() == []


def test_purge_with_nothing_to_delete(endpoint, add_results):
    add_results(200, 200)
    purge_old_results()
    with Session(engine) as session:
        assert len(session.exec(select(CheckResult)).all()) == 2