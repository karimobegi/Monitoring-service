from celery import Celery
from celery.signals import worker_process_init

from app.config import REDIS_URL
from app.db import engine


@worker_process_init.connect
def init_worker(**kwargs):
    engine.dispose()


celery_app = Celery(
    "uptime",
    broker=REDIS_URL,
    include=["app.dispatcher", "app.alerts"],
)

celery_app.conf.beat_schedule = {
    "dispatch_due_checks": {
        "task": "app.dispatcher.dispatch_due_checks",
        "schedule": 10,
    }
}