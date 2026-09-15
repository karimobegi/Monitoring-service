from datetime import datetime, timezone
from sqlmodel import Session, select

from app.auth import get_password_hash
from app.db import engine
from app.models import User, Endpoint

DEMO_EMAIL = "demo@example.com"
DEMO_ENDPOINTS = [
    ("https://example.com", 60),
    ("https://www.wikipedia.org", 120),
    ("https://httpbin.org/status/200", 60),
    ("https://httpbin.org/status/503", 60),   # always down, so incidents appear
]


def main(password: str) -> None:
    with Session(engine) as session:
        user = session.exec(select(User).where(User.email == DEMO_EMAIL)).first()
        if user is None:
            user = User(email=DEMO_EMAIL, hashed_password=get_password_hash(password))
            session.add(user)
            session.commit()
            session.refresh(user)
            print(f"created user {DEMO_EMAIL}")

        for url, interval in DEMO_ENDPOINTS:
            exists = session.exec(
                select(Endpoint).where(Endpoint.user_id == user.id, Endpoint.url == url)
            ).first()
            if exists:
                continue
            session.add(Endpoint(
                user_id=user.id, url=url, interval_seconds=interval, #type: ignore
                next_check_at=datetime.now(timezone.utc),
                monitoring_since=datetime.now(timezone.utc),
            ))
            print(f"added {url}")
        session.commit()


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m scripts.seed_demo <password>")
    main(sys.argv[1])