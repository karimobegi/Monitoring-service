from fastapi import Depends, APIRouter, WebSocket, WebSocketDisconnect, Query, WebSocketException, status
from sqlmodel import Session
from dotenv import load_dotenv
import os
from collections import defaultdict
import redis.asyncio as redis
import json
import logging
import asyncio


from app.models import User
from app.db import get_all_owned_endpoints, engine
from app.auth import user_from_token
from app.config import REDIS_URL


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

async def redis_subscriber() -> None:
    client = redis.from_url(REDIS_URL)
    ps = client.pubsub()
    await ps.subscribe("status")
    try:
        async for message in ps.listen():
            if message["type"] != "message":
                continue
            try:
                payload = json.loads(message["data"])
                eid = payload["endpoint_id"]
                for ws in list(connections.get(eid, set())):
                    try:
                        await ws.send_json(payload)
                    except Exception:
                        pass
            except Exception:
                logging.exception("bad pubsub message: %r", message["data"])

    except asyncio.CancelledError:
        pass
    finally:
        await ps.unsubscribe()
        await ps.aclose()
        await client.aclose()





    
    
