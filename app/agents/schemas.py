from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


class ActionType(str, Enum):
    speak = "speak"
    vote = "vote"
    werewolf_kill = "werewolf_kill"
    seer_check = "seer_check"
    witch_save = "witch_save"
    witch_poison = "witch_poison"
    hunter_shoot = "hunter_shoot"
    guard_protect = "guard_protect"
    run_for_sheriff = "run_for_sheriff"
    sheriff_vote = "sheriff_vote"
    sheriff_assign = "sheriff_assign"


class SpeakAction(BaseModel):
    action_type: Literal[ActionType.speak] = ActionType.speak
    content: str = Field(..., min_length=1, description="发言内容，使用中文")


class VoteAction(BaseModel):
    action_type: Literal[ActionType.vote] = ActionType.vote
    target_seat_no: int | None = Field(default=None, description="投票目标座位号，None 表示弃票")


class WerewolfKillAction(BaseModel):
    action_type: Literal[ActionType.werewolf_kill] = ActionType.werewolf_kill
    target_seat_no: int = Field(ge=1, description="击杀目标座位号")


class SeerCheckAction(BaseModel):
    action_type: Literal[ActionType.seer_check] = ActionType.seer_check
    target_seat_no: int = Field(ge=1, description="查验目标座位号")


class WitchAction(BaseModel):
    action_type: Literal[ActionType.witch_save, ActionType.witch_poison] = Field(
        ..., description="女巫行动类型：witch_save 救人 / witch_poison 毒人"
    )
    target_seat_no: int = Field(ge=1, description="目标座位号")


class HunterShootAction(BaseModel):
    action_type: Literal[ActionType.hunter_shoot] = ActionType.hunter_shoot
    target_seat_no: int = Field(ge=1, description="开枪目标座位号")


class GuardProtectAction(BaseModel):
    action_type: Literal[ActionType.guard_protect] = ActionType.guard_protect
    target_seat_no: int = Field(ge=1, description="守护目标座位号")


class RunForSheriffAction(BaseModel):
    action_type: Literal[ActionType.run_for_sheriff] = ActionType.run_for_sheriff
    run: bool = Field(..., description="是否参选警长")
    content: str | None = Field(default=None, description="参选警长时的公开发言")


class SheriffVoteAction(BaseModel):
    action_type: Literal[ActionType.sheriff_vote] = ActionType.sheriff_vote
    target_seat_no: int | None = Field(default=None, description="警长投票目标，None 表示弃票")


class SheriffAssignAction(BaseModel):
    action_type: Literal[ActionType.sheriff_assign] = ActionType.sheriff_assign
    target_seat_no: int = Field(ge=1, description="警徽移交给的目标座位号")


AgentAction = Annotated[
    Union[
        SpeakAction,
        VoteAction,
        WerewolfKillAction,
        SeerCheckAction,
        WitchAction,
        HunterShootAction,
        GuardProtectAction,
        RunForSheriffAction,
        SheriffVoteAction,
        SheriffAssignAction,
    ],
    Field(discriminator="action_type"),
]


class AgentDecision(BaseModel):
    """Agent 的结构化决策输出。"""

    action: AgentAction
    reasoning_summary: str = Field(
        default="",
        description="中文简短推理总结，用于日志记录",
    )
