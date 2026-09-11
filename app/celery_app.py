import structlog
from celery import Celery, Task
from celery.signals import setup_logging, task_postrun, task_prerun, worker_process_init

from app.config import REDIS_URL
from app.db import engine
from app.logging_config import configure_logging


@setup_logging.connect
def init_logging(**kwargs):
    # Connecting to this signal stops Celery installing its own log handlers
    configure_logging()


@worker_process_init.connect
def init_worker(**kwargs):
    engine.dispose()


@task_prerun.connect
def bind_task_context(task_id: str, task: Task, **kwargs):
    # Every log line emitted while this task runs carries its id and name
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(task_id=task_id, task_name=task.name)


@task_postrun.connect
def clear_task_context(**kwargs):
    structlog.contextvars.clear_contextvars()


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