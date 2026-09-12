import pytest
from fastapi import WebSocketDisconnect
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

from app.auth import create_access_token
from app.realtime import connections, handle_message

def test_ws_rejects_missing_token(client):
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws"):
            pass
    assert exc.value.code == 1008


def test_ws_rejects_invalid_token(client):
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws?token=not-a-jwt"):
            pass
    assert exc.value.code == 1008


def test_ws_rejects_token_for_deleted_user(client):
    # Valid signature, but no such user: user_from_token returns None
    orphan = create_access_token({"sub": "99999"})
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"/ws?token={orphan}"):
            pass
    assert exc.value.code == 1008


def test_ws_accepts_valid_token(client, token):
    with client.websocket_connect(f"/ws?token={token}"):
        pass  # no exception means the handshake succeeded

def test_connect_registers_socket_for_owned_endpoints(client, token, endpoint):
    with client.websocket_connect(f"/ws?token={token}"):
        assert len(connections[endpoint.id]) == 1


def test_disconnect_removes_socket(client, token, endpoint):
    with client.websocket_connect(f"/ws?token={token}"):
        pass
    assert connections.get(endpoint.id, set()) == set()


def test_socket_not_registered_for_other_users_endpoints(client, token):
    from sqlmodel import Session
    from app.db import engine
    from app.models import User, Endpoint
    from datetime import datetime, timezone

    with Session(engine) as session:
        other = User(email="other@example.com", hashed_password="x")
        session.add(other)
        session.commit()
        session.refresh(other)
        ep = Endpoint(
            user_id=other.id, #type: ignore
            url="https://other.test/health",
            next_check_at=datetime.now(timezone.utc),
            monitoring_since=datetime.now(timezone.utc) - timedelta(seconds=200)

        )
        session.add(ep)
        session.commit()
        session.refresh(ep)
        other_id = ep.id

    with client.websocket_connect(f"/ws?token={token}"):
        assert connections.get(other_id, set()) == set() #type: ignore

def frame(payload: str):
    return {"type": "message", "data": payload}


@pytest.mark.asyncio
async def test_forwards_to_registered_socket():
    ws = AsyncMock()
    connections[1].add(ws)
    await handle_message(frame('{"endpoint_id": 1, "status_code": 200, "is_up": true}'))
    ws.send_json.assert_awaited_once()


@pytest.mark.asyncio
async def test_does_not_forward_to_other_endpoints_socket():
    ws = AsyncMock()
    connections[1].add(ws)
    await handle_message(frame('{"endpoint_id": 2, "status_code": 200, "is_up": true}'))
    ws.send_json.assert_not_awaited()


@pytest.mark.asyncio
async def test_ignores_subscribe_confirmation():
    ws = AsyncMock()
    connections[1].add(ws)
    await handle_message({"type": "subscribe", "data": 1})
    ws.send_json.assert_not_awaited()


@pytest.mark.asyncio
async def test_malformed_frame_does_not_raise():
    ws = AsyncMock()
    connections[1].add(ws)
    await handle_message(frame("not json"))
    ws.send_json.assert_not_awaited()


@pytest.mark.asyncio
async def test_one_failing_socket_does_not_block_another():
    bad, good = AsyncMock(), AsyncMock()
    bad.send_json.side_effect = RuntimeError("socket gone")
    connections[1].update({bad, good})
    await handle_message(frame('{"endpoint_id": 1, "status_code": 200, "is_up": true}'))
    good.send_json.assert_awaited_once()