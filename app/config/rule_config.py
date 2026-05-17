from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RuleConfig(BaseModel):
    """游戏规则细项配置，可持久化到 GameState。"""

    player_count: Literal[6, 12] = 6
    enable_sheriff: bool = False
    sheriff_vote_weight: float = Field(default=1.5, gt=1.0)
    enable_tie_pk: bool = True
    witch_can_self_save_first_night: bool = True
    witch_save_once: bool = True
    witch_poison_once: bool = True
    guard_can_self_guard: bool = True
    guard_can_guard_same_target_consecutively: bool = False
    guard_witch_same_target_death: bool = False
    hunter_can_shoot_when_poisoned: bool = False
    idiot_reveal_on_vote: bool = True
    speech_retention_rounds: int = Field(default=2, ge=0, description="Agent 视图中保留当前轮以及最近 N-1 轮完整发言，更早轮次压缩为摘要，0=全部压缩")


def default_rule_config(player_count: int) -> RuleConfig:
    if player_count not in (6, 12):
        raise ValueError(f"Unsupported player count: {player_count}, must be 6 or 12")
    return RuleConfig(
        player_count=player_count,
        enable_sheriff=(player_count == 12),
    )
