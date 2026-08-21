from fastapi import FastAPI, Depends, HTTPException, status, Query
from typing import Annotated
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import Session, select
from db import get_session, add_endpoint, get_owned_endpoint, get_all_owned_endpoints, update_endpoint_in_db, delete_endpoint_in_db
from models import User, UserCreate, UserRead, EndpointRead, EndpointCreate, EndpointUpdate
from auth import get_password_hash, authenticate_user, create_access_token, Token, get_current_user
from sqlalchemy.exc import IntegrityError

app = FastAPI()

@app.post("/register", response_model=UserRead)
def register(user_create: UserCreate, session: Session = Depends(get_session)):
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
def login(form_data: Annotated[OAuth2PasswordRequestForm, Depends()], session: Session = Depends(get_session)):
    email = form_data.username.strip().lower()
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
    rows = get_all_owned_endpoints(user_id, session, limit, offset)
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
    