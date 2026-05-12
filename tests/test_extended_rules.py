from __future__ import annotations

from app.agents.schemas import (
    ActionType,
    AgentDecision,
    HunterShootAction,
    SeerCheckAction,
    SpeakAction,
    VoteAction,
    WerewolfKillAction,
    WitchAction,
)
from app.config.role_setups import RoleCount, RoleSetup
from app.engine import NightActionSet, initialize_game, resolve_night
from app.graph.main_graph import run_night_phase, run_vote_phase
from app.state.schemas import Camp, GamePhase, Role
from app.state.view_builder import PlayerView


class QueueAgent:
    def __init__(self, role: Role, decisions: list[AgentDecision]):
        self._role = role
        self._decisions = list(decisions)
        self.views: list[PlayerView] = []

    @property
    def role(self) -> Role:
        return self._role

    def decide(self, view: PlayerView) -> AgentDecision:
        self.views.append(view)
        if self._decisions:
            return self._decisions.pop(0)
        if "vote" in view.available_actions:
            return AgentDecision(action=VoteAction(target_seat_no=None))
        if "speak" in view.available_actions:
            return AgentDecision(action=SpeakAction(content="我先过。"))
        if "hunter_shoot" in view.available_actions:
            return AgentDecision(action=HunterShootAction(target_seat_no=1))
        return AgentDecision(action=SpeakAction(content="无动作。"))


def _custom_setup(roles: list[Role]) -> RoleSetup:
    counts: list[RoleCount] = []
    for role in roles:
        for item in counts:
            if item.role == role:
                item.count += 1
                break
        else:
            counts.append(RoleCount(role=role, count=1))
    return RoleSetup(player_count=len(roles), role_counts=counts)


def _agents(game_state, decisions: dict[int, list[AgentDecision]]) -> dict[int, QueueAgent]:
    return {
        player.seat_no: QueueAgent(player.role, decisions.get(player.seat_no, []))
        for player in game_state.players
    }


def test_witch_save_can_only_be_used_once_by_default():
    gs = initialize_game("witch-once")
    gs.public_state.round = 1
    first = resolve_night(
        gs,
        NightActionSet(wolf_kill_target=3, witch_save_target=3),
    )
    assert first.deaths == []
    assert gs.runtime_state.witch_save_used is True

    gs.public_state.round = 2
    second = resolve_night(
        gs,
        NightActionSet(wolf_kill_target=3, witch_save_target=3),
    )
    assert second.deaths == [3]


def test_guard_cannot_guard_same_target_consecutively_by_default():
    gs = initialize_game("guard-repeat")
    gs.runtime_state.guard_last_target = 3
    result = resolve_night(
        gs,
        NightActionSet(wolf_kill_target=3, guard_target=3),
    )
    assert result.deaths == [3]
    assert result.death_reasons[3] == "wolf_kill"


def test_hunter_vote_death_can_shoot():
    setup = _custom_setup(
        [Role.werewolf, Role.seer, Role.witch, Role.hunter, Role.villager, Role.villager]
    )
    gs = initialize_game("hunter-shot", setup)
    gs.public_state.phase = GamePhase.vote
    agents = _agents(
        gs,
        {
            1: [AgentDecision(action=VoteAction(target_seat_no=4))],
            2: [AgentDecision(action=VoteAction(target_seat_no=4))],
            3: [AgentDecision(action=VoteAction(target_seat_no=4))],
            4: [
                AgentDecision(action=VoteAction(target_seat_no=1)),
                AgentDecision(action=HunterShootAction(target_seat_no=1)),
            ],
        },
    )

    run_vote_phase(gs, agents)

    assert 4 in gs.public_state.dead_players
    assert 1 in gs.public_state.dead_players
    assert any(event["type"] == "hunter_shot" for event in gs.public_state.public_events)


def test_hunter_poison_death_cannot_shoot_by_default():
    setup = _custom_setup(
        [Role.werewolf, Role.seer, Role.witch, Role.hunter, Role.villager, Role.villager]
    )
    gs = initialize_game("hunter-poison", setup)
    agents = _agents(
        gs,
        {
            1: [AgentDecision(action=WerewolfKillAction(target_seat_no=5))],
            2: [AgentDecision(action=SeerCheckAction(target_seat_no=1))],
            3: [
                AgentDecision(
                    action=WitchAction(
                        action_type=ActionType.witch_poison,
                        target_seat_no=4,
                    )
                )
            ],
            4: [AgentDecision(action=HunterShootAction(target_seat_no=1))],
        },
    )

    run_night_phase(gs, agents)

    assert 4 in gs.public_state.dead_players
    assert not any(event["type"] == "hunter_shot" for event in gs.public_state.public_events)
    assert any(event["type"] == "hunter_no_shot" for event in gs.public_state.public_events)


def test_idiot_vote_elimination_reveals_instead_of_dying():
    setup = _custom_setup(
        [Role.werewolf, Role.seer, Role.witch, Role.idiot, Role.villager, Role.villager]
    )
    gs = initialize_game("idiot-reveal", setup)
    gs.public_state.phase = GamePhase.vote
    agents = _agents(
        gs,
        {
            1: [AgentDecision(action=VoteAction(target_seat_no=4))],
            2: [AgentDecision(action=VoteAction(target_seat_no=4))],
            3: [AgentDecision(action=VoteAction(target_seat_no=4))],
        },
    )

    run_vote_phase(gs, agents)

    idiot = next(player for player in gs.players if player.seat_no == 4)
    assert idiot.status.alive is True
    assert idiot.status.can_vote is False
    assert 4 in gs.runtime_state.idiot_revealed_seats
    assert any(event["type"] == "idiot_revealed" for event in gs.public_state.public_events)


def test_sheriff_vote_weight_changes_exile_result():
    gs = initialize_game("sheriff-weight")
    gs.public_state.phase = GamePhase.vote
    gs.sheriff_seat_no = 1
    agents = _agents(
        gs,
        {
            1: [AgentDecision(action=VoteAction(target_seat_no=5))],
            2: [AgentDecision(action=VoteAction(target_seat_no=6))],
        },
    )

    run_vote_phase(gs, agents)

    assert 5 in gs.public_state.dead_players
    resolved = [event for event in gs.public_state.public_events if event["type"] == "vote_resolved"][-1]
    assert resolved["vote_counts"][5] == 1.5
    assert resolved["vote_counts"][6] == 1.0


def test_tie_pk_second_tie_keeps_everyone_alive():
    gs = initialize_game("pk-tie")
    gs.public_state.phase = GamePhase.vote
    agents = _agents(
        gs,
        {
            1: [
                AgentDecision(action=VoteAction(target_seat_no=5)),
                AgentDecision(action=VoteAction(target_seat_no=5)),
            ],
            2: [
                AgentDecision(action=VoteAction(target_seat_no=6)),
                AgentDecision(action=VoteAction(target_seat_no=6)),
            ],
        },
    )

    run_vote_phase(gs, agents)

    assert 5 not in gs.public_state.dead_players
    assert 6 not in gs.public_state.dead_players
    assert any(event["type"] == "pk_started" for event in gs.public_state.public_events)
    resolved = [event for event in gs.public_state.public_events if event["type"] == "vote_resolved"][-1]
    assert set(resolved["tied_seats"]) == {5, 6}
