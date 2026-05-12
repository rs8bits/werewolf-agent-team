from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

DATABASE_URL = os.getenv("WEREWOLF_DATABASE_URL", "sqlite:///./data/werewolf.db")

# Auto-create data directory for default SQLite path
if DATABASE_URL.startswith("sqlite:///"):
    db_path_str = DATABASE_URL[len("sqlite:///"):]
    if db_path_str.startswith("./"):
        Path(db_path_str).parent.mkdir(parents=True, exist_ok=True)

_connect_args = {"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Session:
    """FastAPI dependency: yields an SQLAlchemy session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
