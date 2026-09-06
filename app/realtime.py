from fastapi import Depends, APIRouter, WebSocket, WebSocketDisconnect
from sqlmodel import Session
from dotenv import load_dotenv
import os
from collections import defaultdict
import redis.asyncio as redis
import json
import logging


from models import User
from auth import get_current_user
from db import get_all_owned_endpoints, engine

load_dotenv()
REDIS_URL = os.environ["REDIS_URL"]

router = APIRouter()
connections: dict[int, set[WebSocket]] = defaultdict(set)

@router.websocket("/ws")
async def dashboard(websocket: WebSocket):
    await websocket.accept()
    user = 
    with Session(engine) as session:
        rows = get_all_owned_endpoints(user.id, session)
        ids = [e.id for e in rows]
    # session closed here — we're done with the db
    for eid in ids:
        connections[eid].add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        for eid in ids:
            connections[eid].discard(websocket)


                    





    
    
