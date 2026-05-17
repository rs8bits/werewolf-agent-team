from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config.rule_config import RuleConfig, default_rule_config


class TestRuleConfig:
    def test_six_player_defaults_disable_sheriff(self):
        cfg = default_rule_config(6)
        assert cfg.player_count == 6
        assert cfg.enable_sheriff is False
        assert cfg.enable_tie_pk is True
        assert cfg.witch_save_once is True
        assert cfg.witch_poison_once is True

    def test_twelve_player_defaults_enable_sheriff(self):
        cfg = default_rule_config(12)
        assert cfg.player_count == 12
        assert cfg.enable_sheriff is True
        assert cfg.sheriff_vote_weight == 1.5

    def test_default_speech_retention_keeps_current_and_previous_round(self):
        cfg = default_rule_config(6)
        assert cfg.speech_retention_rounds == 2

    def test_unsupported_default_count_raises(self):
        with pytest.raises(ValueError):
            default_rule_config(9)

    def test_model_rejects_unsupported_count(self):
        with pytest.raises(ValidationError):
            RuleConfig(player_count=9)
