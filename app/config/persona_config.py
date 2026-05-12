from __future__ import annotations

from pydantic import BaseModel, Field


class PersonaProfile(BaseModel):
    """Configurable agent persona that maps to runtime resources.

    All ability dimensions are normalised to [0, 1].
    """

    intelligence: float = Field(default=0.5, ge=0.0, le=1.0)
    memory: float = Field(default=0.5, ge=0.0, le=1.0)
    experience: float = Field(default=0.5, ge=0.0, le=1.0)
    rhetoric: float = Field(default=0.5, ge=0.0, le=1.0)
    risk_appetite: float = Field(default=0.5, ge=0.0, le=1.0)
    discipline: float = Field(default=0.5, ge=0.0, le=1.0)

    model: str = Field(default="qwen-plus", min_length=1)
    context_window: int = Field(default=8192, ge=512)
    reasoning_budget: int = Field(default=1024, ge=64)
