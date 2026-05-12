from __future__ import annotations

from app.agents.base_agent import BaseAgent
from app.agents.seer_agent import SeerAgent
from app.agents.villager_agent import VillagerAgent
from app.agents.werewolf_agent import WerewolfAgent
from app.agents.witch_agent import WitchAgent
from app.llm.client import LLMClient
from app.state.schemas import Role

_AGENT_CLASSES: dict[Role, type[BaseAgent]] = {
    Role.werewolf: WerewolfAgent,
    Role.seer: SeerAgent,
    Role.witch: WitchAgent,
    Role.villager: VillagerAgent,
}


def create_agent(role: Role, llm_client: LLMClient) -> BaseAgent:
    agent_cls = _AGENT_CLASSES.get(role)
    if agent_cls is None:
        raise ValueError(
            f"不支持的角色 '{role.value}'，无法创建 Agent。"
            f"当前支持的角色: {sorted(r.value for r in _AGENT_CLASSES)}"
        )
    return agent_cls(llm_client=llm_client)
