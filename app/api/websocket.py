from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.db import get_db
from app.services.event_bus import game_event_bus
from app.services.game_session import GameSessionService

router = APIRouter()


@router.websocket("/ws/games/{game_id}/events")
async def ws_game_events(
    websocket: WebSocket,
    game_id: str,
    db: Session = Depends(get_db),
):
    """WebSocket：发送当前快照，并持续推送运行中的事件。"""
    await websocket.accept()

    service = GameSessionService(db)
    game_state = service.get_game(game_id)
    if game_state is None:
        await websocket.send_json({"error": f"对局不存在: {game_id}"})
        await asyncio.sleep(0.1)
        await websocket.close()
        return

    subscriber = game_event_bus.subscribe(game_id)
    try:
        events = service.list_events(game_id)
        await websocket.send_json(
            {
                "type": "snapshot",
                "game_id": game_id,
                "game": game_state.model_dump(),
                "events": events,
            }
        )
        # Yield so the snapshot is flushed before live events arrive.
        await asyncio.sleep(0)

        while True:
            try:
                message = await asyncio.wait_for(subscriber.queue.get(), timeout=25)
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping", "game_id": game_id})
                continue
            await websocket.send_json(message)
    except WebSocketDisconnect:
        pass
    finally:
        game_event_bus.unsubscribe(game_id, subscriber)
