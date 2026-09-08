import redis
import json

from app.config import REDIS_URL, STATUS_CHANNEL


client = redis.Redis.from_url(REDIS_URL)

def publish_status_change(endpoint_id: int, status_code: int | None, checked_at: str) -> None:
    data_dict = {
        "endpoint_id": endpoint_id,
        "status_code": status_code,
        "checked_at": checked_at
    }
    json_string = json.dumps(data_dict)
    client.publish(STATUS_CHANNEL, json_string)

