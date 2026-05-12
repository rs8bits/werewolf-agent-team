from app.agents.base_agent import AgentDecisionError, BaseAgent
from app.agents.factory import create_agent
from app.agents.guard_agent import GuardAgent
from app.agents.hunter_agent import HunterAgent
from app.agents.idiot_agent import IdiotAgent
from app.agents.prompts import (
    BASE_SYSTEM_PROMPT,
    GUARD_SYSTEM_PROMPT,
    HUNTER_SYSTEM_PROMPT,
    IDIOT_SYSTEM_PROMPT,
    SEER_SYSTEM_PROMPT,
    VILLAGER_SYSTEM_PROMPT,
    WEREWOLF_SYSTEM_PROMPT,
    WITCH_SYSTEM_PROMPT,
    get_role_prompt,
)
from app.agents.schemas import (
    ActionType,
    AgentDecision,
    GuardProtectAction,
    HunterShootAction,
    RunForSheriffAction,
    SeerCheckAction,
    SheriffAssignAction,
    SheriffVoteAction,
    SpeakAction,
    VoteAction,
    WerewolfKillAction,
    WitchAction,
)
from app.agents.seer_agent import SeerAgent
from app.agents.villager_agent import VillagerAgent
from app.agents.werewolf_agent import WerewolfAgent
from app.agents.witch_agent import WitchAgent

__all__ = [
    # Schemas
    "ActionType",
    "SpeakAction",
    "VoteAction",
    "WerewolfKillAction",
    "SeerCheckAction",
    "WitchAction",
    "HunterShootAction",
    "GuardProtectAction",
    "RunForSheriffAction",
    "SheriffVoteAction",
    "SheriffAssignAction",
    "AgentDecision",
    # Base
    "BaseAgent",
    "AgentDecisionError",
    # Role agents
    "WerewolfAgent",
    "SeerAgent",
    "WitchAgent",
    "VillagerAgent",
    "HunterAgent",
    "IdiotAgent",
    "GuardAgent",
    # Factory
    "create_agent",
    # Prompts
    "BASE_SYSTEM_PROMPT",
    "WEREWOLF_SYSTEM_PROMPT",
    "SEER_SYSTEM_PROMPT",
    "WITCH_SYSTEM_PROMPT",
    "VILLAGER_SYSTEM_PROMPT",
    "HUNTER_SYSTEM_PROMPT",
    "IDIOT_SYSTEM_PROMPT",
    "GUARD_SYSTEM_PROMPT",
    "get_role_prompt",
]
