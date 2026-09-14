import redis
import json

from app.config import REDIS_URL, STATUS_CHANNEL


client = redis.Redis.from_url(REDIS_URL)

def publish_status_change(endpoint_id: int, user_id: int, status_code: int | None,
                          checked_at: str, is_up: bool) -> None:
    client.publish(STATUS_CHANNEL, json.dumps({
        "endpoint_id": endpoint_id,
        "user_id": user_id,
        "status_code": status_code,
        "checked_at": checked_at,
        "is_up": is_up,
    }))

