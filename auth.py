from typing import Annotated
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel
from jwt.exceptions import InvalidTokenError
import jwt
from pwdlib import PasswordHash
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from dotenv import load_dotenv
import os
from models import User, UserCreate
from sqlmodel import Session, select
from db import get_session



class Token(BaseModel):
    access_token: str
    token_type: str

load_dotenv()
SECRET_KEY = os.environ["SECRET_KEY"]
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = timedelta(minutes=int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30")))

password_hash = PasswordHash.recommended()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

DUMMY_HASH = password_hash.hash("dummypassword")#security

def get_current_user(token: Annotated[str, Depends(oauth2_scheme)], session: Annotated[Session, Depends(get_session)]) -> User:
    credentials_exception = HTTPException(
        status_code = status.HTTP_401_UNAUTHORIZED,
        detail = "Could not validate credentials",
        headers = {"WWW-Authenticate": "Bearer"}
    )
    try:
        payload = jwt.decode(token, SECRET_KEY,algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise credentials_exception
        
        user_id = int(user_id)
        user = session.exec(select(User).where(User.id == user_id)).first()
        if user is None:
            raise credentials_exception
        return user

    except (InvalidTokenError, ValueError):
        raise credentials_exception



def get_password_hash(password: str):
    return password_hash.hash(password)

def get_user(email: str, session: Session):
    return session.exec(select(User).where(User.email == email)).first()

def verify_password(password, hashed_password):
    return password_hash.verify(password, hashed_password)

def authenticate_user(email: str, password: str, session: Session):
    user = get_user(email, session)
    if not(user):
        verify_password(password, DUMMY_HASH)
        return None

    if verify_password(password, user.hashed_password):
        return user
    else:
        return None

def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    if not(expires_delta):
        expires_delta = ACCESS_TOKEN_EXPIRE_MINUTES
    
    expire = expires_delta + datetime.now(timezone.utc)
    to_encode["exp"] = expire
    encoded = jwt.encode(to_encode, SECRET_KEY, algorithm = ALGORITHM)
    return encoded
