from fastapi import FastAPI, Depends, HTTPException, status
from typing import Annotated
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import Session, select
from db import get_session
from models import User, UserCreate, UserRead
from auth import get_password_hash, authenticate_user, create_access_token, Token
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




