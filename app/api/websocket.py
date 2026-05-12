from __future__ import annotations

from fastapi import APIRouter, WebSocket

from app.services.game_session import GameSessionService

router = APIRouter()


@router.websocket("/ws/games/{game_id}/events")
async def ws_game_events(
    websocket: WebSocket,
    game_id: str,
):
    """WebSocket：连接后发送当前事件快照，然后关闭。

    简化实现 —— 不做实时推送订阅。
    """
    await websocket.accept()

    # Create a synchronous DB session inside the async handler
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        service = GameSessionService(db)
        game_state = service.get_game(game_id)
        if game_state is None:
            await websocket.send_json({"error": f"对局不存在: {game_id}"})
        else:
            events = service.list_events(game_id)
            await websocket.send_json(
                {
                    "game_id": game_id,
                    "phase": game_state.public_state.phase.value,
                    "round": game_state.public_state.round,
                    "events": events,
                }
            )
    finally:
        db.close()

    await websocket.close()
