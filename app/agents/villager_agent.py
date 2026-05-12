from __future__ import annotations

from app.agents.base_agent import BaseAgent
from app.state.schemas import Role


class VillagerAgent(BaseAgent):
    """平民 Agent。无夜间技能，依靠发言和投票。"""

    @property
    def role(self) -> Role:
        return Role.villager
