from __future__ import annotations

from collections.abc import Sequence

from app.config.rule_config import RuleConfig, default_rule_config
from app.config.role_setups import RoleSetup, six_player_setup
from app.state.schemas import (
    GamePhase,
    GameState,
    PlayerState,
    PlayerType,
    PublicState,
    TruthState,
    Role,
    camp_of,
)


def initialize_game(
    game_id: str,
    setup: RoleSetup | None = None,
    *,
    player_names: Sequence[str] | None = None,
    player_types: Sequence[PlayerType] | None = None,
    rule_config: RuleConfig | None = None,
    agent_mode: str = "scripted",
    model: str | None = None,
    seed: int | None = None,
) -> GameState:
    role_setup = setup or six_player_setup()
    rules = rule_config or default_rule_config(role_setup.player_count)
    seat_configs = role_setup.seat_configs(seed=seed)

    if player_names is not None and len(player_names) != role_setup.player_count:
        raise ValueError(
            f"Expected {role_setup.player_count} player names, got {len(player_names)}"
        )
    if player_types is not None and len(player_types) != role_setup.player_count:
        raise ValueError(
            f"Expected {role_setup.player_count} player types, got {len(player_types)}"
        )

    players: list[PlayerState] = []
    for index, seat_config in enumerate(seat_configs):
        role = seat_config.role
        player_type = player_types[index] if player_types is not None else seat_config.player_type
        players.append(
            PlayerState(
                seat_no=seat_config.seat_no,
                name=player_names[index] if player_names is not None else f"P{seat_config.seat_no}",
                player_type=player_type,
                role=role,
                camp=camp_of(role),
            )
        )

    alive_players = [player.seat_no for player in players]
    real_identities = {player.seat_no: player.role for player in players}
    wolf_team = [
        player.seat_no for player in players if player.role == Role.werewolf
    ]

    return GameState(
        game_id=game_id,
        agent_mode=agent_mode,
        model=model,
        rule_config=rules,
        public_state=PublicState(
            round=0,
            phase=GamePhase.setup,
            alive_players=alive_players,
            dead_players=[],
            public_events=[{"type": "game_initialized", "player_count": role_setup.player_count}],
        ),
        players=players,
        truth_state=TruthState(
            real_identities=real_identities,
            wolf_team=wolf_team,
        ),
    )
