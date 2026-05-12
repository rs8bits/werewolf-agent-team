from __future__ import annotations

import argparse

from app.db import SessionLocal, engine
from app.models import Base
from app.services.game_session import GameSessionService


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a limited Qwen-backed werewolf smoke game.")
    parser.add_argument("--model", default="qwen3.5-27b")
    parser.add_argument("--player-count", type=int, default=6, choices=[6, 12])
    parser.add_argument("--cycles", type=int, default=1)
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        service = GameSessionService(db)
        game_state = service.create_game(
            player_count=args.player_count,
            agent_mode="llm",
            model=args.model,
        )
        for _ in range(args.cycles):
            if game_state.public_state.phase.value == "ended":
                break
            game_state = service.run_cycle(game_state.game_id)

        events = service.list_events(game_state.game_id)
        event_types = [event["event"].get("type") for event in events]
        print(f"game_id={game_state.game_id}")
        print(f"model={args.model}")
        print(f"player_count={args.player_count}")
        print(f"phase={game_state.public_state.phase.value}")
        print(f"winner={game_state.winner.value if game_state.winner else None}")
        print(f"event_count={len(events)}")
        print(f"event_types={event_types}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
