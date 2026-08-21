from fastapi import FastAPI, Depends
from sqlmodel import Field, Session, SQLModel, create_engine, select
from dotenv import load_dotenv
import os
from models import User, Endpoint, EndpointCreate, EndpointUpdate
from datetime import datetime, timezone
from sqlalchemy.exc import IntegrityError

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://karimobegi@localhost:5432/uptime")
engine = create_engine(DATABASE_URL, echo = True) 


def get_session():
    with Session(engine) as session:
        yield session

def add_user(user: User, session: Session):
    session.add(user)
    session.commit()

def add_endpoint(user_id: int, url: str, interval: int, session: Session):
    try:
        endpoint = Endpoint(user_id = user_id, url = url, interval_seconds = interval, next_check_at=datetime.now(timezone.utc))
    except ValueError as e:
        raise ValueError(f"Validation failed: {e}")

    try: 
        session.add(endpoint)
        session.commit()
    except IntegrityError:
            session.rollback()
            raise ValueError(f"Database integrity error. Check if user_id {user_id} exists.")
    session.refresh(endpoint)
    return endpoint


def get_owned_endpoint(endpoint_id: int, user_id: int, session: Session):
     endpoint = session.exec(select(Endpoint).where(Endpoint.id == endpoint_id, Endpoint.user_id == user_id)).first()
     return endpoint

def get_all_owned_endpoints(user_id: int, session: Session, limit: int = 30, offset: int = 0):
     rows = session.exec((select(Endpoint).where(Endpoint.user_id == user_id)).order_by(Endpoint.id).limit(limit).offset(offset)).all() #type: ignore
     return rows

def update_endpoint_in_db(endpoint_id: int, user_id: int, session: Session, update_data: dict):
    endpoint = get_owned_endpoint(endpoint_id, user_id, session)
    if endpoint is None:
        return None
    endpoint.sqlmodel_update(update_data)
    session.add(endpoint)
    session.commit()
    session.refresh(endpoint)
    return endpoint

def delete_endpoint_in_db(endpoint_id: int, user_id: int, session: Session):
    endpoint = get_owned_endpoint(endpoint_id, user_id, session)
    if endpoint is None:
        return None
    session.delete(endpoint)
    session.commit()
    return True

    