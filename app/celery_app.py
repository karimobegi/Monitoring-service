import structlog
from celery import Celery, Task
from celery.signals import setup_logging, task_postrun, task_prerun, worker_process_init, worker_ready
import os

from app.config import REDIS_URL
from app.db import engine
from app.logging_config import configure_logging

WORKER_METRICS_PORT = 9808

@worker_ready.connect
def start_metrics_server(**kwargs):
    # Runs once, in the worker's parent process; the prefork children only write metric files
    if "PROMETHEUS_MULTIPROC_DIR" not in os.environ:
        return
    from prometheus_client import CollectorRegistry, multiprocess, start_http_server

    registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(registry)
    start_http_server(WORKER_METRICS_PORT, registry=registry)
    structlog.get_logger(__name__).info("metrics_server_started", port=WORKER_METRICS_PORT)

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