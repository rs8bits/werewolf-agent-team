from app.config.settings import LLMConfig, load_config


class TestLLMConfigDefaults:
    def test_dataclass_defaults(self):
        cfg = LLMConfig()
        assert cfg.api_key == ""
        assert cfg.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
        assert cfg.model == "qwen-plus"
        assert cfg.timeout_seconds == 60


class TestLoadConfig:
    def test_loads_from_env_vars(self, monkeypatch):
        monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key-123")
        monkeypatch.setenv("DASHSCOPE_BASE_URL", "https://test.example.com/v1")
        monkeypatch.setenv("DASHSCOPE_MODEL", "qwen-turbo")
        monkeypatch.setenv("DASHSCOPE_TIMEOUT_SECONDS", "30")

        cfg = load_config()
        assert cfg.api_key == "test-key-123"
        assert cfg.base_url == "https://test.example.com/v1"
        assert cfg.model == "qwen-turbo"
        assert cfg.timeout_seconds == 30

    def test_defaults_when_env_not_set(self, monkeypatch):
        for var in (
            "DASHSCOPE_API_KEY",
            "DASHSCOPE_BASE_URL",
            "DASHSCOPE_MODEL",
            "DASHSCOPE_TIMEOUT_SECONDS",
        ):
            monkeypatch.delenv(var, raising=False)

        cfg = load_config()
        assert cfg.api_key == ""
        assert cfg.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
        assert cfg.model == "qwen-plus"
        assert cfg.timeout_seconds == 60

    def test_api_key_empty_by_default(self, monkeypatch):
        monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
        cfg = load_config()
        assert cfg.api_key == ""
