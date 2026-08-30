import json
from collections import defaultdict
from typing import Dict, List, Set

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from fastapi.websockets import WebSocketState

from app.core.security import decode_token

log = structlog.get_logger()
router = APIRouter(tags=["WebSocket"])


class ConnectionManager:
    def __init__(self):
        # merchant_id -> set of active WebSocket connections
        self._connections: Dict[str, Set[WebSocket]] = defaultdict(set)

    async def connect(self, merchant_id: str, ws: WebSocket):
        await ws.accept()
        self._connections[merchant_id].add(ws)
        log.info("ws_connected", merchant_id=merchant_id, total=len(self._connections[merchant_id]))

    def disconnect(self, merchant_id: str, ws: WebSocket):
        self._connections[merchant_id].discard(ws)
        log.info("ws_disconnected", merchant_id=merchant_id)

    async def broadcast_to_merchant(self, merchant_id: str, data: dict):
        dead = set()
        for ws in self._connections.get(merchant_id, set()):
            try:
                if ws.client_state == WebSocketState.CONNECTED:
                    await ws.send_text(json.dumps(data))
            except Exception as e:
                log.warning("ws_send_failed", merchant_id=merchant_id, error=str(e))
                dead.add(ws)
        for ws in dead:
            self.disconnect(merchant_id, ws)

    async def broadcast_to_admin(self, data: dict):
        """Broadcast to all admin sessions (stored under key 'admin')."""
        await self.broadcast_to_merchant("admin", data)


manager = ConnectionManager()


@router.websocket("/ws/merchant/{merchant_id}")
async def merchant_ws(
    websocket: WebSocket,
    merchant_id: str,
    token: str = Query(...),
):
    # Validate JWT before accepting
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            await websocket.close(code=4001)
            return
        user_role = payload.get("role")
        user_id = payload.get("sub")
    except Exception:
        await websocket.close(code=4001)
        return

    # Admins can connect to any merchant; merchants only to their own
    if user_role not in ("admin",):
        # Verify merchant ownership
        from app.db.session import async_session
        from app.db.models import Merchant
        from sqlalchemy import select
        async with async_session() as db:
            result = await db.execute(
                select(Merchant).where(Merchant.user_id == user_id)
            )
            merchant = result.scalar_one_or_none()
            if not merchant or str(merchant.id) != merchant_id:
                await websocket.close(code=4003)
                return

    await manager.connect(merchant_id, websocket)
    try:
        while True:
            # Keep connection alive; echo ping
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(merchant_id, websocket)


@router.websocket("/ws/admin")
async def admin_ws(
    websocket: WebSocket,
    token: str = Query(...),
):
    try:
        payload = decode_token(token)
        if payload.get("role") != "admin":
            await websocket.close(code=4003)
            return
    except Exception:
        await websocket.close(code=4001)
        return

    await manager.connect("admin", websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect("admin", websocket)
