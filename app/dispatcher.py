from datetime import datetime, timezone
from sqlmodel import Session, select, desc
from sqlalchemy import text
import httpx
from sqlalchemy.exc import OperationalError
import structlog
import socket

from app.db import engine
from app.events import publish_status_change
from app.models import CheckResult, AlertConfig, AlertState, AlertChannel
from app.celery_app import celery_app
from app.alerts import send_email_alert, send_webhook_alert

log = structlog.get_logger(__name__)

def queue_alert(config: AlertConfig, endpoint_id: int, url: str,
                timestamp: str, is_recovery: bool) -> None:
    args = (config.target, endpoint_id, url, timestamp, is_recovery)
    if config.channel == AlertChannel.EMAIL:
        send_email_alert.delay(*args) #type: ignore
    elif config.channel == AlertChannel.WEBHOOK:
        send_webhook_alert.delay(*args) #type: ignore
    else:
        log.warning("unknown_alert_channel", channel=str(config.channel), alert_config_id=config.id)
        return
    log.info(
        "alert_queued",
        alert_config_id=config.id,
        channel=config.channel.value,
        kind="recovery" if is_recovery else "down",
    )

@celery_app.task
def dispatch_due_checks():
    probe_time = datetime.now(timezone.utc)

    with Session(engine) as session:
        result = session.execute(text("""
            UPDATE endpoint
            SET next_check_at = now() + (interval_seconds * INTERVAL '1 second')
            WHERE is_active AND next_check_at <= now()
            RETURNING id, url
        """))
        rows = result.all()
        session.commit()

    for row in rows:
        perform_check.apply_async(args=[row.id, row.url, probe_time.isoformat()]) #type: ignore
    if rows:
        log.info("endpoints_claimed", count=len(rows), endpoint_ids=[r.id for r in rows])

def classify_connect_error(exc: httpx.ConnectError) -> str:
    """Tell DNS failures from refused connections by walking the exception chain."""
    cause: BaseException | None = exc
    while cause is not None:
        if isinstance(cause, socket.gaierror):
            return "dns_failure"
        if isinstance(cause, ConnectionRefusedError):
            return "connection_refused"
        cause = cause.__cause__ or cause.__context__
    return "connect_error"

@celery_app.task(
    autoretry_for=(OperationalError,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def perform_check(endpoint_id: int, url: str, checked_at: str):
    structlog.contextvars.bind_contextvars(endpoint_id=endpoint_id)
    error = None
    try:
        response = httpx.get(url, timeout=10.0)
        status_code = response.status_code
        response_time_ms = int(response.elapsed.total_seconds() * 1000)
    except httpx.TimeoutException:
        error = "timeout"
        status_code=None
        response_time_ms=None
    except httpx.ConnectError as exc:
        error = classify_connect_error(exc)
        status_code = None
        response_time_ms = None
    except httpx.HTTPError:
        error="unknown"
        status_code=None
        response_time_ms=None

    is_up = status_code is not None and 200 <= status_code < 400
    log.info(
        "check_completed",
        url=url,
        status_code=status_code,
        error=error,
        response_time_ms=response_time_ms,
        is_up=is_up,
    )

    with Session(engine) as session:
        prev_result = session.exec(select(CheckResult).where(CheckResult.endpoint_id == endpoint_id).order_by(desc(CheckResult.checked_at)).limit(1)).first()
        prev_status = prev_result.status_code if prev_result is not None else None
        check_result = CheckResult(endpoint_id = endpoint_id, checked_at =datetime.fromisoformat(checked_at), status_code=status_code, error=error, response_time_ms=response_time_ms)
        session.add(check_result)
        if prev_result is not None and prev_status != status_code:
            try:
                publish_status_change(endpoint_id, status_code, checked_at)
                
            except Exception:
                log.exception("status_publish_failed", endpoint_id=endpoint_id)
        alert_rows = session.exec(select(AlertConfig).where(AlertConfig.endpoint_id == endpoint_id, AlertConfig.is_active == True)).all()

        for row in alert_rows:
            if row.id is None: continue
            state_row = session.exec(select(AlertState).where(AlertState.config_id==row.id)).first()
            if state_row is None:
                state_row = AlertState(config_id = row.id)

            if is_up:
                if state_row.alert_sent:
                    queue_alert(row, endpoint_id, url, checked_at, True)

                state_row.current_streak = 0
                state_row.alert_sent = False
            else:
                state_row.current_streak += 1
                if state_row.current_streak >= row.threshold and not state_row.alert_sent:
                    queue_alert(row, endpoint_id, url, checked_at, False)
                    state_row.alert_sent = True
                    state_row.last_alert_at = datetime.now(timezone.utc)

            session.add(state_row)
        session.commit()
                