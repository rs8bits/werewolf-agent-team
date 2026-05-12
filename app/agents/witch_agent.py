from __future__ import annotations

from app.agents.base_agent import BaseAgent
from app.state.schemas import Role


class WitchAgent(BaseAgent):
    """女巫 Agent。拥有一瓶解药和一瓶毒药。"""

    @property
    def role(self) -> Role:
        return Role.witch
