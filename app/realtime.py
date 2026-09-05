from fastapi import Depends, APIRouter, WebSocket
from sqlmodel import Session
from dotenv import load_dotenv
import os
from collections import defaultdict


from models import User
from auth import get_current_user
from db import get_all_owned_endpoints, engine


router = APIRouter()
connections: dict[int, set[WebSocket]] = defaultdict(set)

@router.get("/endpoints")
def list_endpoint(user: User = Depends(get_current_user)):
    with Session(engine) as session:
        user_id = user.id
        assert user_id is not None
        rows = get_all_owned_endpoints(user_id, session)
    
