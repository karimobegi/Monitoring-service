from fastapi import FastAPI, Depends
from sqlmodel import Field, Session, SQLModel, create_engine, select
from dotenv import load_dotenv
import os
from models import User

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://karimobegi@localhost:5432/uptime")
engine = create_engine(DATABASE_URL, echo = True) 


def get_session():
    with Session(engine) as session:
        yield session

def add_user(user: User, session: Session):
    session.add(user)
    session.commit()



