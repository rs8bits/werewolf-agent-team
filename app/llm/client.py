from typing import Any

from openai import OpenAI

from app.config.settings import LLMConfig, load_config
from app.llm.schemas import ChatMessage, ChatRequest, ChatResponse


class LLMClient:
    """Lazy-initialised OpenAI-compatible client for DashScope / Qwen.

    Does not make any network request at import time.
    """

    def __init__(self, config: LLMConfig | None = None, openai_client: Any | None = None):
        self.config = config or load_config()
        if not self.config.api_key:
            raise ValueError(
                "DASHSCOPE_API_KEY is not set. "
                "Create a .env file from .env.example and fill in your API key, "
                "or set the DASHSCOPE_API_KEY environment variable."
            )
        self._client: OpenAI | Any | None = openai_client

    @property
    def client(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI(
                api_key=self.config.api_key,
                base_url=self.config.base_url,
                timeout=float(self.config.timeout_seconds),
            )
        return self._client

    def chat_json(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs,
    ) -> ChatResponse:
        response = self.client.chat.completions.create(
            model=self.config.model,
            messages=[m.model_dump() for m in messages],
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
        choice = response.choices[0]
        return ChatResponse(
            content=choice.message.content or "",
            finish_reason=choice.finish_reason,
            usage={
                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                "total_tokens": response.usage.total_tokens if response.usage else 0,
            },
        )
