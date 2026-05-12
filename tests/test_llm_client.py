from unittest.mock import MagicMock

import pytest

from app.llm.client import LLMClient
from app.llm.schemas import ChatMessage, ChatResponse
from app.config.settings import LLMConfig


class TestLLMClientInit:
    def test_raises_when_api_key_empty(self):
        cfg = LLMConfig(api_key="")
        with pytest.raises(ValueError, match="DASHSCOPE_API_KEY"):
            LLMClient(config=cfg)

    def test_no_network_on_init(self):
        cfg = LLMConfig(api_key="test-key")
        client = LLMClient(config=cfg)
        assert client._client is None


class TestLLMClientChatJson:
    def _make_cfg(self) -> LLMConfig:
        return LLMConfig(
            api_key="test-key",
            base_url="https://test.example.com/v1",
            model="qwen-plus",
            timeout_seconds=60,
        )

    def test_returns_chat_response(self):
        cfg = self._make_cfg()
        fake_choice = MagicMock()
        fake_choice.message.content = "Hello, world!"
        fake_choice.finish_reason = "stop"
        fake_completion = MagicMock()
        fake_completion.choices = [fake_choice]
        fake_completion.usage.prompt_tokens = 10
        fake_completion.usage.completion_tokens = 5
        fake_completion.usage.total_tokens = 15

        mock_openai = MagicMock()
        mock_openai.chat.completions.create.return_value = fake_completion

        client = LLMClient(config=cfg, openai_client=mock_openai)
        result = client.chat_json(
            [ChatMessage(role="user", content="Hi")],
        )

        assert isinstance(result, ChatResponse)
        assert result.content == "Hello, world!"
        assert result.finish_reason == "stop"
        assert result.usage is not None
        assert result.usage["total_tokens"] == 15

    def test_passes_model_and_messages(self):
        cfg = self._make_cfg()
        fake_choice = MagicMock()
        fake_choice.message.content = "ok"
        fake_choice.finish_reason = "stop"
        fake_completion = MagicMock()
        fake_completion.choices = [fake_choice]
        fake_completion.usage = None

        mock_openai = MagicMock()
        mock_openai.chat.completions.create.return_value = fake_completion

        client = LLMClient(config=cfg, openai_client=mock_openai)
        client.chat_json(
            [ChatMessage(role="system", content="You are helpful.")],
            temperature=0.3,
            max_tokens=512,
        )

        call_kwargs = mock_openai.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == "qwen-plus"
        assert call_kwargs["temperature"] == 0.3
        assert call_kwargs["max_tokens"] == 512

    def test_content_none_fallback(self):
        cfg = self._make_cfg()
        fake_choice = MagicMock()
        fake_choice.message.content = None
        fake_choice.finish_reason = "length"
        fake_completion = MagicMock()
        fake_completion.choices = [fake_choice]
        fake_completion.usage = None

        mock_openai = MagicMock()
        mock_openai.chat.completions.create.return_value = fake_completion

        client = LLMClient(config=cfg, openai_client=mock_openai)
        result = client.chat_json([ChatMessage(role="user", content="Hi")])

        assert result.content == ""
