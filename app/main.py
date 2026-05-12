from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create DB tables on startup
    from app.db import engine
    from app.models import Base

    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="Werewolf Agent Team", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok"}


from app.api.routes_game import router as game_router  # noqa: E402
from app.api.websocket import router as ws_router  # noqa: E402

app.include_router(game_router)
app.include_router(ws_router)
