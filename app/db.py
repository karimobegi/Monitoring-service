from sqlmodel import Session, create_engine, select
from datetime import datetime, timezone
from sqlalchemy.exc import IntegrityError
from collections.abc import Sequence

from app.models import User, Endpoint, AlertChannel, AlertConfig, AlertState, AlertConfigRead
from app.config import DATABASE_URL

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

def add_alert_to_db(threshold: int, channel: AlertChannel, target: str, is_active: bool, endpoint_id: int, user_id: int, session: Session):
    try:
        alert_config = AlertConfig(threshold=threshold, channel = channel, target=target, is_active=is_active, user_id = user_id, endpoint_id = endpoint_id)
        session.add(alert_config)
        session.flush()   
        alert_state = AlertState(config_id = alert_config.id) #type: ignore
        session.add(alert_state)
        session.commit()

    except (IntegrityError, ValueError):
        session.rollback()
        raise ValueError(f"Database integrity error. Check if user_id {user_id} and endpoint_id {endpoint_id} exist")
    session.refresh(alert_config)
    return alert_config

def get_alerts_per_owned_endpoint(endpoint_id: int, user_id: int, session: Session) -> Sequence[AlertConfig]:
    alert_config_rows = session.exec(select(AlertConfig).where(AlertConfig.endpoint_id==endpoint_id, AlertConfig.user_id== user_id)).all()
    return alert_config_rows

def get_owned_alert(alert_id: int, endpoint_id: int, user_id: int, session: Session) -> AlertConfig | None:
    return session.exec(
        select(AlertConfig).where(
            AlertConfig.id == alert_id,
            AlertConfig.user_id == user_id,
            AlertConfig.endpoint_id == endpoint_id
        )
    ).first()

def update_alert_in_db(alert: AlertConfig, update_data: dict, session: Session):
    alert.sqlmodel_update(update_data)
    session.add(alert)
    session.commit()
    session.refresh(alert)
    return alert

def delete_alert_in_db(alert: AlertConfig, session: Session):
    session.delete(alert)
    session.commit()
