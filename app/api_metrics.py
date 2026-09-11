"""Metrics recorded by the API (single uvicorn process, so no multiprocess mode)."""
from prometheus_client import Counter, Gauge, Histogram

HTTP_REQUESTS = Counter(
    "monitor_http_requests_total",
    "HTTP requests handled by the API",
    ["method", "route", "status"],
)
HTTP_REQUEST_DURATION = Histogram(
    "monitor_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "route"],
)
WEBSOCKET_CONNECTIONS = Gauge(
    "monitor_websocket_connections",
    "Open dashboard WebSocket connections",
)
