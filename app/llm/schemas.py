from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str = Field(..., description="One of system, user, assistant")
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    temperature: float = 0.7
    max_tokens: int = 1024


class ChatResponse(BaseModel):
    content: str
    role: str = "assistant"
    finish_reason: str | None = None
    usage: dict | None = None
