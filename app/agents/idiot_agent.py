from __future__ import annotations

from app.agents.base_agent import BaseAgent
from app.state.schemas import Role


class IdiotAgent(BaseAgent):
    @property
    def role(self) -> Role:
        return Role.idiot
