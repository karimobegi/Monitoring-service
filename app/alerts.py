from textwrap import dedent
import smtplib
from email.message import EmailMessage
from fastapi import HTTPException
import httpx
import structlog
from celery.signals import task_failure, task_retry
from sqlalchemy import text
from sqlmodel import Session

from app.celery_app import celery_app
from app.config import SMTP_FROM, SMTP_HOST, SMTP_PASSWORD, SMTP_PORT, SMTP_USER
from app.worker_metrics import ALERT_DELIVERY_FAILURES, ALERTS_SENT
from app.db import engine

log = structlog.get_logger(__name__)

@celery_app.task(
    acks_late=True,
    autoretry_for=(smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError, OSError),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=5,
)
def send_email_alert(config_id: int, target: str, endpoint_id: int, url: str, timestamp: str, is_recovery: bool) -> None:
    kind = "recovery" if is_recovery else "down"
    structlog.contextvars.bind_contextvars(endpoint_id=endpoint_id, kind=kind)
    msg = EmailMessage()
    msg["From"] = SMTP_FROM
    msg["To"] = target

    if is_recovery:
        msg["Subject"] = f"RECOVERED: endpoint {endpoint_id} is back online"
        body = dedent(f"""
            Hello,

            Good news! The endpoint with ID {endpoint_id} has recovered at: {timestamp}.
            URL: {url}

            Best regards,
            Monitoring System
        """)
    else:
        msg["Subject"] = f"ALERT: endpoint {endpoint_id} is down"
        body = dedent(f"""
            Warning,

            The endpoint with ID {endpoint_id} has failed a health check at: {timestamp}.
            URL: {url}
            
            Please investigate the issue immediately.

            Best regards,
            Monitoring System
        """)
    msg.set_content(body)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as s:
        if SMTP_USER:
            s.starttls()
            s.login(SMTP_USER, SMTP_PASSWORD)
        s.send_message(msg)
    log.info("alert_sent", channel="email")
    ALERTS_SENT.labels(channel="email", kind=kind).inc()

@celery_app.task(
    acks_late=True,
    autoretry_for=(httpx.HTTPStatusError, httpx.RequestError),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=5,    
)
def send_webhook_alert(config_id: int, target: str, endpoint_id: int, url: str, timestamp: str, is_recovery: bool) -> None:
    kind = "recovery" if is_recovery else "down"
    structlog.contextvars.bind_contextvars(endpoint_id=endpoint_id, kind=kind)
    event = "endpoint_recovered" if is_recovery else "endpoint_down"
    payload_dict = {
        "event": event,
        "endpoint_id": endpoint_id,
        "url": url,
        "timestamp": timestamp
    }
    try:
        response = httpx.post(target, json=payload_dict, timeout=10.0)
        response.raise_for_status()
        log.info("alert_sent", channel="webhook", target_host=httpx.URL(target).host, status_code=response.status_code)
        ALERTS_SENT.labels(channel="webhook", kind=kind).inc()
    except httpx.HTTPStatusError as e:
        if e.response.status_code >= 500 or e.response.status_code == 429:
            raise 
        log.error("webhook_rejected", status_code=e.response.status_code, target_host=httpx.URL(target).host)
        ALERT_DELIVERY_FAILURES.labels(channel="webhook", reason="rejected").inc()
        return  

CHANNEL_BY_TASK = {send_email_alert.name: "email", send_webhook_alert.name: "webhook"}  # type: ignore

@task_retry.connect
def count_alert_retry(sender=None, **kwargs):
    channel = CHANNEL_BY_TASK.get(getattr(sender, "name", ""))
    if channel:
        ALERT_DELIVERY_FAILURES.labels(channel=channel, reason="retry").inc()


def mark_alert_undelivered(config_id: int) -> None:
    """A down alert gave up: record that the user was never told, so the next failed check alerts again."""
    with Session(engine) as session:
        session.execute(
            text("UPDATE alertstate SET alert_sent = false WHERE config_id = :config_id AND alert_sent"),
            {"config_id": config_id},
        )
        session.commit()


@task_failure.connect
def handle_alert_exhausted(sender=None, args=None, **_):
    channel = CHANNEL_BY_TASK.get(getattr(sender, "name", ""))
    if not channel or not args:
        return
    ALERT_DELIVERY_FAILURES.labels(channel=channel, reason="exhausted").inc()

    config_id, *_rest, is_recovery = args  # task args: (config_id, ..., is_recovery)
    if not is_recovery:
        mark_alert_undelivered(config_id)
        log.warning("alert_undelivered", alert_config_id=config_id, channel=channel)