"""Fixed-window rate limiting backed by Redis.

Counts live in Redis, not in process memory, so limits hold across API restarts
and across multiple API containers.
"""
import time

import redis
import structlog
from fastapi import HTTPException, Request, status

from app.api_metrics import RATE_LIMITED
from app.config import REDIS_URL

log = structlog.get_logger(__name__)
client = redis.Redis.from_url(REDIS_URL)


def client_ip(request: Request) -> str:
    # Behind a reverse proxy this is the proxy's address unless uvicorn trusts its headers
    return request.client.host if request.client else "unknown"


def enforce(name: str, identity: str, limit: int, window_seconds: int) -> None:
    """Count one request for `identity` under limit `name`; raise 429 once `limit` is exceeded."""
    now = time.time()
    window = int(now // window_seconds)
    key = f"ratelimit:{name}:{identity}:{window}"

    pipe = client.pipeline()  # MULTI/EXEC: both commands apply together
    pipe.incr(key)
    pipe.expire(key, window_seconds)
    try:
        count, _ = pipe.execute()
    except redis.RedisError:
        # Fail open: a Redis outage should not lock every user out of the API
        log.warning("rate_limit_unavailable", limit_name=name)
        return

    if count > limit:
        RATE_LIMITED.labels(limit=name).inc()
        log.info("rate_limited", limit_name=name, count=count)
        retry_after = window_seconds - int(now) % window_seconds
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests",
            headers={"Retry-After": str(retry_after)},
        )
