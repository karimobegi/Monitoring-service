from celery import Celery
from app.models import CheckResult
from datetime import datetime, timezone
from sqlmodel import Session
import os
from sqlalchemy import text
from celery.signals import worker_process_init
import httpx
from sqlalchemy.exc import OperationalError
from dotenv import load_dotenv
from app.db import engine


load_dotenv()

@worker_process_init.connect
def init_worker(**kwargs):
    engine.dispose()
    
celery_app = Celery(
    "uptime",
    broker=os.environ["REDIS_URL"],
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
        perform_check.apply_async(args=[row.id, row.url, probe_time.isoformat()])

@celery_app.task(
    autoretry_for=(OperationalError,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def perform_check(endpoint_id: int, url: str, checked_at: str):
    error = None
    try:
        response = httpx.get(url, timeout=10.0)
        status_code = response.status_code
        response_time_ms = int(response.elapsed.total_seconds() * 1000)
    except httpx.TimeoutException:
        error = "timeout"
        status_code=None
        response_time_ms=None
    except httpx.ConnectError:
        error = "dns_failure"
        status_code=None
        response_time_ms=None
    except httpx.HTTPError:
        error="unknown"
        status_code=None
        response_time_ms=None
    with Session(engine) as session:
        check_result = CheckResult(endpoint_id = endpoint_id, checked_at =datetime.fromisoformat(checked_at), status_code=status_code, error=error, response_time_ms=response_time_ms)
        session.add(check_result)
        session.commit()

celery_app.conf.beat_schedule = {
"dispatch_due_checks": {"task": "dispatcher.dispatch_due_checks",
		"schedule": 10
        }
    }






        
