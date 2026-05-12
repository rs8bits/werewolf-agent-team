from __future__ import annotations

from app.agents.base_agent import BaseAgent
from app.state.schemas import Role


class GuardAgent(BaseAgent):
    @property
    def role(self) -> Role:
        return Role.guard
