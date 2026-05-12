from __future__ import annotations

from app.agents.base_agent import BaseAgent
from app.state.schemas import Role


class WerewolfAgent(BaseAgent):
    """狼人 Agent。夜晚可击杀，白天隐藏身份。"""

    @property
    def role(self) -> Role:
        return Role.werewolf
