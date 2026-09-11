"""Shared fixtures for the check worker and alert dispatch tests.

Tests run locally (not in Docker) against a separate Postgres database,
because the dispatcher uses Postgres-only SQL.
"""
# ruff: noqa: E402
import os

# Must be set before any `app` import: app.config reads these at import time
# and app.db creates the engine from DATABASE_URL immediately.
os.environ["DATABASE_URL"] = os.getenv("TEST_DATABASE_URL", "postgresql://localhost:5432/monitor_test")
os.environ["REDIS_URL"] = "redis://localhost:6379/15"
os.environ["SECRET_KEY"] = "test-secret"

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlmodel import Session, select

from app.db import engine
from app.dispatcher import perform_check
from app.models import AlertChannel, AlertConfig, CheckResult, Endpoint, User

ROOT = Path(__file__).resolve().parents[1]
TABLES = '"user", endpoint, checkresult, alertconfig, alertstate'


@pytest.fixture(scope="session", autouse=True)
def schema():
    # These fixtures drop and truncate tables, so never point them at a real database
    assert engine.url.database and engine.url.database.endswith("_test"), (
        f"refusing to run tests against database {engine.url.database!r}"
    )
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")


@pytest.fixture(autouse=True)
def clean_tables(schema):
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))


@pytest.fixture(autouse=True)
def no_redis_publish(monkeypatch):
    # Status-change publishing feeds the WebSocket (tested in Week 4); keep Redis out
    monkeypatch.setattr("app.dispatcher.publish_status_change", MagicMock())


class QueuedAlerts:
    """Stands in for the Celery send tasks and records what perform_check queued."""

    def __init__(self):
        self.email = MagicMock()
        self.webhook = MagicMock()

    def kinds(self, channel: str = "email") -> list[str]:
        fake = getattr(self, channel)
        return ["recovery" if call.args[-1] else "down" for call in fake.delay.call_args_list]

@pytest.fixture(autouse=True)
def queued(monkeypatch) -> QueuedAlerts:
    # Autouse: an unmocked .delay() would try to reach the Celery broker and hang
    alerts = QueuedAlerts()
    monkeypatch.setattr("app.dispatcher.send_email_alert", alerts.email)
    monkeypatch.setattr("app.dispatcher.send_webhook_alert", alerts.webhook)
    return alerts


@pytest.fixture
def endpoint() -> Endpoint:
    with Session(engine) as session:
        user = User(email="owner@example.com", hashed_password="not-used")
        session.add(user)
        session.commit()
        session.refresh(user)
        assert user.id is not None

        ep = Endpoint(
            user_id=user.id,
            url="https://service.test/health",
            next_check_at=datetime.now(timezone.utc),
        )
        session.add(ep)
        session.commit()
        session.refresh(ep)
        return ep


@pytest.fixture
def add_alert(endpoint):
    def _add(threshold: int = 3, channel: AlertChannel = AlertChannel.EMAIL, is_active: bool = True) -> AlertConfig:
        with Session(engine) as session:
            config = AlertConfig(
                user_id=endpoint.user_id,
                endpoint_id=endpoint.id,
                threshold=threshold,
                channel=channel,
                target="ops@example.com" if channel == AlertChannel.EMAIL else "https://hooks.test/alert",
                is_active=is_active,
            )
            session.add(config)
            session.commit()
            session.refresh(config)
            return config

    return _add


@pytest.fixture
def run_check(endpoint, respx_mock):
    """Run perform_check once. `outcome` is an HTTP status code or an httpx exception."""
    route = respx_mock.get(endpoint.url)
    clock = [datetime(2026, 1, 1, tzinfo=timezone.utc)]

    def _run(outcome: int | Exception) -> None:
        if isinstance(outcome, int):
            route.mock(return_value=httpx.Response(outcome))
        else:
            route.mock(side_effect=outcome)
        clock[0] += timedelta(seconds=60)  # each check is later than the previous one
        perform_check(endpoint.id, endpoint.url, clock[0].isoformat())

    return _run


@pytest.fixture
def results(endpoint):
    def _results() -> list[CheckResult]:
        with Session(engine) as session:
            query = (
                select(CheckResult)
                .where(CheckResult.endpoint_id == endpoint.id)
                .order_by(CheckResult.checked_at)  # type: ignore
            )
            return list(session.exec(query).all())

    return _results
