from textwrap import dedent
import smtplib
from email.message import EmailMessage
from fastapi import HTTPException
import httpx
import logging

from app.celery_app import celery_app
from app.config import SMTP_FROM, SMTP_HOST, SMTP_PASSWORD, SMTP_PORT, SMTP_USER

@celery_app.task(
    acks_late=True,
    autoretry_for=(smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError, OSError),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=5,
)
def send_email_alert(target: str, endpoint_id: int, url: str, timestamp: str, is_recovery: bool) -> None:
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
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
        if SMTP_USER:
            s.starttls()
            s.login(SMTP_USER, SMTP_PASSWORD)
        s.send_message(msg)

@celery_app.task(
    acks_late=True,
    autoretry_for=(httpx.HTTPStatusError, httpx.RequestError),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=5,    
)
def send_webhook_alert(target: str, endpoint_id: int, url: str, timestamp: str, is_recovery: bool) -> None:
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
    except httpx.HTTPStatusError as e:
        if e.response.status_code >= 500 or e.response.status_code == 429:
            raise 
        logging.error("webhook rejected: %s %s", e.response.status_code, target)
        return  



