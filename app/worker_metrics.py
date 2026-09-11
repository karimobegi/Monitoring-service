"""Metrics recorded by the Celery worker.

The worker runs prefork child processes, each with its own memory. With
PROMETHEUS_MULTIPROC_DIR set, prometheus_client writes samples to files in that
directory, and the metrics server in the parent process (started in
celery_app.py) sums them across all children.
"""
from prometheus_client import Counter, Histogram

CHECK_OUTCOMES = (
    "up",
    "http_error",
    "timeout",
    "connection_refused",
    "dns_failure",
    "connect_error",
    "unknown",
)

CHECKS = Counter(
    "monitor_checks_total",
    "Health checks performed, by outcome",
    ["outcome"],
)
CHECK_DURATION = Histogram(
    "monitor_check_duration_seconds",
    "Time spent on the HTTP request of a health check",
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
CHECK_LAG = Histogram(
    "monitor_check_lag_seconds",
    "Delay between an endpoint being claimed by the dispatcher and its check starting",
    buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60, 120),
)
ALERTS_QUEUED = Counter(
    "monitor_alerts_queued_total",
    "Alerts handed to Celery for delivery",
    ["channel", "kind"],
)
ALERTS_SENT = Counter(
    "monitor_alerts_sent_total",
    "Alerts delivered successfully",
    ["channel", "kind"],
)
ALERT_DELIVERY_FAILURES = Counter(
    "monitor_alert_delivery_failures_total",
    "Failed alert deliveries. reason: retry = attempt failed and will be retried, "
    "exhausted = gave up after all retries, rejected = webhook answered 4xx",
    ["channel", "reason"],
)

# Create every label combination up front, so each series is exported at 0 before its first event
for _outcome in CHECK_OUTCOMES:
    CHECKS.labels(outcome=_outcome)
for _channel in ("email", "webhook"):
    for _kind in ("down", "recovery"):
        ALERTS_QUEUED.labels(channel=_channel, kind=_kind)
        ALERTS_SENT.labels(channel=_channel, kind=_kind)
    for _reason in ("retry", "exhausted", "rejected"):
        ALERT_DELIVERY_FAILURES.labels(channel=_channel, reason=_reason)
