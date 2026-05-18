from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.agents import AgentDecisionError
from app.config.rule_config import RuleConfig, default_rule_config
from app.db import get_db
from app.services.game_session import GameSessionService

router = APIRouter(prefix="/games", tags=["games"])


# ── Request schemas ────────────────────────────────────────────────────────

class CreateGameRequest(BaseModel):
    player_count: Literal[6, 12] = Field(default=6, description="玩家人数")
    player_names: list[str] | None = Field(
        default=None,
        description="玩家姓名（可选，默认 P1...；长度必须等于 player_count）",
    )
    agent_mode: Literal["scripted", "llm"] = Field(default="scripted")
    model: str | None = Field(default=None, description="LLM 模型名，例如 qwen3.5-27b")
    rule_config: dict[str, Any] | None = Field(default=None, description="规则配置覆盖")
    seed: int | None = Field(default=None, description="座位随机种子（可选，用于测试）")
    human_seats: list[int] | None = Field(
        default=None, description="真人座位号列表（例如 [1, 3]），仅 6 人局支持"
    )

    @model_validator(mode="after")
    def player_names_must_match_count(self) -> "CreateGameRequest":
        if self.player_names is not None and len(self.player_names) != self.player_count:
            raise ValueError("player_names length must equal player_count")
        return self

    @model_validator(mode="after")
    def human_seats_only_for_6_player(self) -> "CreateGameRequest":
        if self.human_seats is not None and self.player_count != 6:
            raise ValueError("human_seats only supported for player_count=6")
        return self


class RunUntilFinishedRequest(BaseModel):
    max_cycles: int = Field(default=50, ge=1, le=200, description="最大轮数")


def _agent_decision_http_error(exc: AgentDecisionError) -> HTTPException:
    return HTTPException(status_code=502, detail=f"Agent 决策失败：{exc}")


# ── Routes ─────────────────────────────────────────────────────────────────

@router.post("")
def create_game(
    body: CreateGameRequest = CreateGameRequest(),
    db: Session = Depends(get_db),
):
    """创建一局狼人杀对局。默认使用脚本 Agent，可显式选择 LLM Agent。"""
    service = GameSessionService(db)
    rules = default_rule_config(body.player_count)
    if body.rule_config:
        rules = RuleConfig.model_validate({**rules.model_dump(), **body.rule_config})
    try:
        game_state = service.create_game(
            player_names=body.player_names,
            player_count=body.player_count,
            agent_mode=body.agent_mode,
            model=body.model,
            rule_config=rules,
            seed=body.seed,
            human_seats=body.human_seats,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
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
    except AgentDecisionError as exc:
        raise _agent_decision_http_error(exc)
    except ValueError as exc:
        status = 400 if "DASHSCOPE_API_KEY" in str(exc) else 404
        raise HTTPException(status_code=status, detail=str(exc))
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
    except AgentDecisionError as exc:
        raise _agent_decision_http_error(exc)
    except ValueError as exc:
        status = 400 if "DASHSCOPE_API_KEY" in str(exc) else 404
        raise HTTPException(status_code=status, detail=str(exc))
    return game_state.model_dump()


@router.get("/{game_id}/events")
def list_events(game_id: str, db: Session = Depends(get_db)):
    """查询对局的结构化事件日志。"""
    service = GameSessionService(db)
    # Verify game exists
    if service.get_game(game_id) is None:
        raise HTTPException(status_code=404, detail=f"对局不存在: {game_id}")
    return service.list_events(game_id)


@router.get("/{game_id}/players/{seat_no}/view")
def get_player_view(game_id: str, seat_no: int, db: Session = Depends(get_db)):
    """查询玩家私有视图（信息隔离，不含 truth_state）。"""
    service = GameSessionService(db)
    view = service.get_player_view(game_id, seat_no)
    if view is None:
        raise HTTPException(status_code=404, detail=f"对局或玩家不存在: {game_id}/{seat_no}")
    return view


@router.post("/{game_id}/players/{seat_no}/actions")
def submit_human_action(
    game_id: str,
    seat_no: int,
    body: dict[str, Any],
    db: Session = Depends(get_db),
):
    """真人玩家提交动作，提交后自动推进到下一个阻塞点。"""
    service = GameSessionService(db)
    try:
        game_state = service.submit_human_action(game_id, seat_no, body)
    except AgentDecisionError as exc:
        raise _agent_decision_http_error(exc)
    except ValueError as exc:
        detail = str(exc)
        if "没有等待真人操作" in detail:
            raise HTTPException(status_code=409, detail=detail)
        if "当前等待" in detail or "操作类型" in detail or "不在可用操作" in detail:
            raise HTTPException(status_code=409, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"无效的请求体：{exc}")
    return game_state.model_dump()
