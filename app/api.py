from fastapi import FastAPI, Depends, HTTPException, status, Query, Request, Response
from typing import Annotated
import uuid
import structlog
import time
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, select, func
from sqlalchemy.exc import IntegrityError
import asyncio
from contextlib import asynccontextmanager
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.auth import get_password_hash, authenticate_user, create_access_token, Token, get_current_user
from app.db import get_session, add_endpoint, get_owned_endpoint, get_endpoints_with_status, update_endpoint_in_db, delete_endpoint_in_db, add_alert_to_db, get_alerts_per_owned_endpoint, get_owned_alert, update_alert_in_db, delete_alert_in_db
from app.models import User, UserCreate, UserRead, EndpointRead, EndpointCreate, EndpointUpdate, AlertConfigCreate, AlertConfigRead, AlertConfigUpdate
from app.realtime import redis_subscriber, router as realtime_router
from app.logging_config import configure_logging
from app.api_metrics import HTTP_REQUEST_DURATION, HTTP_REQUESTS
from app.config import MAX_ENDPOINTS_PER_USER
from app.rate_limit import client_ip, enforce

configure_logging()

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(redis_subscriber())
    yield
    task.cancel()

app = FastAPI(lifespan=lifespan)
app.include_router(realtime_router)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

@app.middleware("http")
async def bind_request_context(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response

@app.middleware("http")
async def record_request_metrics(request: Request, call_next):
    started = time.perf_counter()
    status = "500"  # stays 500 if the handler raises
    try:
        response = await call_next(request)
        status = str(response.status_code)
        return response
    finally:
        # Label by route template (/endpoints/{endpoint_id}), never the raw path,
        # or every id becomes a new time series. Unmatched paths and static files -> "other".
        route = getattr(request.scope.get("route"), "path", "other")
        HTTP_REQUESTS.labels(method=request.method, route=route, status=status).inc()
        HTTP_REQUEST_DURATION.labels(method=request.method, route=route).observe(time.perf_counter() - started)


@app.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.post("/register", response_model=UserRead)
def register(request: Request, user_create: UserCreate, session: Session = Depends(get_session)):
    enforce("register_ip", client_ip(request), limit=5, window_seconds=3600)
    email = user_create.email.strip().lower()
    existing = session.exec(select(User).where(User.email == email)).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    user = User(email=email, hashed_password=get_password_hash(user_create.password))

    try:
        session.add(user)
        session.commit()
        session.refresh(user)
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=400, detail="Email already registered")
    return user

@app.post("/token", response_model=Token)
def login(request: Request, form_data: Annotated[OAuth2PasswordRequestForm, Depends()], session: Session = Depends(get_session)):
    email = form_data.username.strip().lower()
    enforce("login_ip", client_ip(request), limit=20, window_seconds=60)
    enforce("login_email", email, limit=5, window_seconds=60)
    password = form_data.password

    user = authenticate_user(email, password, session)
    if not user: 
        raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
    data = {"sub": str(user.id)}
    token = create_access_token(data)
    
    return Token(access_token=token, token_type="bearer")


@app.post("/endpoints", response_model=EndpointRead)
def set_endpoint(endpoint_create: EndpointCreate, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    user_id = user.id
    assert user_id is not None
    try:
        endpoint = add_endpoint(user_id, endpoint_create.url, endpoint_create.interval_seconds, session)

    except (ValueError, IntegrityError):
        raise HTTPException(
            status_code = status.HTTP_400_BAD_REQUEST,
            detail="Incorrect details",
        )

    return endpoint
    
@app.get("/endpoints/{endpoint_id}", response_model=EndpointRead)
def get_endpoint(endpoint_id: int, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    user_id = user.id
    assert user_id is not None
    endpoint = get_owned_endpoint(endpoint_id, user_id, session)
    if endpoint is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return endpoint

@app.get("/endpoints", response_model=list[EndpointRead])
def get_all_endpoints(limit: int = Query(default=30, le=100, ge=1), offset: int = Query(default = 0, ge=0), user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    user_id = user.id
    assert user_id is not None
    rows = get_endpoints_with_status(user_id, session, limit, offset)
    return rows

@app.patch("/endpoints/{endpoint_id}", response_model = EndpointRead)
def update_endpoint(endpoint_id: int, endpoint_update: EndpointUpdate, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    update_data = endpoint_update.model_dump(exclude_unset=True)
    user_id = user.id
    assert user_id is not None
    updated = update_endpoint_in_db(endpoint_id, user_id, session, update_data)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return updated

@app.delete("/endpoints/{endpoint_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_endpoint(endpoint_id: int, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    user_id = user.id
    assert user_id is not None
    deleted = delete_endpoint_in_db(endpoint_id, user_id, session)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

@app.post("/endpoints/{endpoint_id}/alerts", response_model=AlertConfigRead)
def add_alert(endpoint_id: int, alert_create: AlertConfigCreate, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    threshold = alert_create.threshold
    channel = alert_create.channel
    target = alert_create.target
    is_active = alert_create.is_active
    user_id = user.id
    assert user_id is not None
    if get_owned_endpoint(endpoint_id, user_id, session) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    try:
        alert_config = add_alert_to_db(threshold, channel, target, is_active, endpoint_id, user_id, session)
        return alert_config

    except (ValueError, IntegrityError):
        raise HTTPException(
            status_code = status.HTTP_400_BAD_REQUEST,
            detail="Incorrect details",
        )
    
@app.get("/endpoints/{endpoint_id}/alerts", response_model=list[AlertConfigRead])
def get_alerts(endpoint_id: int,  user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    user_id = user.id
    assert user_id is not None
    if get_owned_endpoint(endpoint_id, user_id, session) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return get_alerts_per_owned_endpoint(endpoint_id, user_id, session)

@app.patch("/endpoints/{endpoint_id}/alerts/{alert_id}", response_model = AlertConfigRead)
def update_alert(endpoint_id: int, alert_id: int, alert_update: AlertConfigUpdate, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    user_id = user.id
    assert user_id is not None
    if get_owned_endpoint(endpoint_id, user_id, session) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    
    alert = get_owned_alert(alert_id, endpoint_id, user_id, session)
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    update_data = alert_update.model_dump(exclude_unset=True)
    try:
        update_alert_in_db(alert, update_data, session)
    except (ValueError, IntegrityError):
        raise HTTPException(
            status_code = status.HTTP_400_BAD_REQUEST,
            detail="Incorrect details",
        ) 
    return alert

@app.delete("/endpoints/{endpoint_id}/alerts/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_alert(endpoint_id: int, alert_id: int, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    user_id = user.id
    assert user_id is not None
    if get_owned_endpoint(endpoint_id, user_id, session) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    
    alert = get_owned_alert(alert_id, endpoint_id, user_id, session)
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    delete_alert_in_db(alert, session)



    


    