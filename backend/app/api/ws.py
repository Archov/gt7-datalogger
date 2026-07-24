"""WebSocket endpoint streaming live telemetry, lap and session events."""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/ws/live")
async def live(ws: WebSocket) -> None:
    service = ws.app.state.service
    await ws.accept()
    await service.register(ws)
    try:
        while True:
            # Client messages are only pings; the stream is server-push.
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        service.unregister(ws)
