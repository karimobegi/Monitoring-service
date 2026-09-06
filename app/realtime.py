from fastapi import Depends, APIRouter, WebSocket, WebSocketDisconnect, Query, WebSocketException, status
from sqlmodel import Session
from dotenv import load_dotenv
import os
from collections import defaultdict
import redis.asyncio as redis
import json
import logging


from models import User
from db import get_all_owned_endpoints, engine
from auth import user_from_token

load_dotenv()
REDIS_URL = os.environ["REDIS_URL"]

router = APIRouter()
connections: dict[int, set[WebSocket]] = defaultdict(set)

async def ws_user(websocket: WebSocket, token: str | None = Query(default = None)) -> User:
    if token is None:
        raise WebSocketException(code = status.WS_1008_POLICY_VIOLATION)
    with Session(engine) as session:
        user = user_from_token(token, session)
    if user is None or user.id is None:
        raise WebSocketException(code = status.WS_1008_POLICY_VIOLATION)
    return user

@router.websocket("/ws")
async def dashboard(websocket: WebSocket, user: User = Depends(ws_user)):
    await websocket.accept()
    with Session(engine) as session:
        user_id = user.id
        rows = get_all_owned_endpoints(user_id, session) #type: ignore
        ids = [e.id for e in rows if e.id is not None]
    for eid in ids:
        connections[eid].add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        for eid in ids:
            connections[eid].discard(websocket)


                    





    
    
