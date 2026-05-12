from __future__ import annotations

from app.agents.base_agent import BaseAgent
from app.state.schemas import Role


class SeerAgent(BaseAgent):
    """预言家 Agent。夜晚可查验一名玩家的阵营。"""

    @property
    def role(self) -> Role:
        return Role.seer
