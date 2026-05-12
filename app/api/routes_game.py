from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.services.game_session import GameSessionService

router = APIRouter(prefix="/games", tags=["games"])


# ── Request schemas ────────────────────────────────────────────────────────

class CreateGameRequest(BaseModel):
    player_names: list[str] | None = Field(
        default=None,
        min_length=6,
        max_length=6,
        description="6 位玩家姓名（可选，默认 P1-P6）",
    )


class RunUntilFinishedRequest(BaseModel):
    max_cycles: int = Field(default=50, ge=1, le=200, description="最大轮数")


# ── Routes ─────────────────────────────────────────────────────────────────

@router.post("")
def create_game(
    body: CreateGameRequest = CreateGameRequest(),
    db: Session = Depends(get_db),
):
    """创建一局 6 人狼人杀对局（使用脚本 Agent）。"""
    service = GameSessionService(db)
    game_state = service.create_game(player_names=body.player_names)
    return game_state.model_dump()


@router.get("/{game_id}")
def get_game(game_id: str, db: Session = Depends(get_db)):
    """查询对局状态。"""
    service = GameSessionService(db)
    game_state = service.get_game(game_id)
    if game_state is None:
        raise HTTPException(status_code=404, detail=f"对局不存在: {game_id}")
    return game_state.model_dump()


@router.post("/{game_id}/run-cycle")
def run_cycle(game_id: str, db: Session = Depends(get_db)):
    """运行一轮对局（夜晚 → 白天 → 投票）。"""
    service = GameSessionService(db)
    try:
        game_state = service.run_cycle(game_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return game_state.model_dump()


@router.post("/{game_id}/run-until-finished")
def run_until_finished(
    game_id: str,
    body: RunUntilFinishedRequest = RunUntilFinishedRequest(),
    db: Session = Depends(get_db),
):
    """运行至对局结束或达到最大轮数。"""
    service = GameSessionService(db)
    try:
        game_state = service.run_until_finished(game_id, max_cycles=body.max_cycles)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return game_state.model_dump()


@router.get("/{game_id}/events")
def list_events(game_id: str, db: Session = Depends(get_db)):
    """查询对局的结构化事件日志。"""
    service = GameSessionService(db)
    # Verify game exists
    if service.get_game(game_id) is None:
        raise HTTPException(status_code=404, detail=f"对局不存在: {game_id}")
    return service.list_events(game_id)
