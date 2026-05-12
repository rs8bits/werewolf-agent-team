import pytest
from pydantic import ValidationError

from app.config.persona_config import PersonaProfile


class TestPersonaProfileDefaults:
    def test_default_intelligence_is_0_5(self):
        p = PersonaProfile()
        assert p.intelligence == 0.5

    def test_default_memory_is_0_5(self):
        p = PersonaProfile()
        assert p.memory == 0.5

    def test_default_experience_is_0_5(self):
        p = PersonaProfile()
        assert p.experience == 0.5

    def test_default_rhetoric_is_0_5(self):
        p = PersonaProfile()
        assert p.rhetoric == 0.5

    def test_default_risk_appetite_is_0_5(self):
        p = PersonaProfile()
        assert p.risk_appetite == 0.5

    def test_default_discipline_is_0_5(self):
        p = PersonaProfile()
        assert p.discipline == 0.5

    def test_default_model_is_qwen_plus(self):
        p = PersonaProfile()
        assert p.model == "qwen-plus"

    def test_default_context_window_is_8192(self):
        p = PersonaProfile()
        assert p.context_window == 8192

    def test_default_reasoning_budget_is_1024(self):
        p = PersonaProfile()
        assert p.reasoning_budget == 1024


class TestPersonaProfileValidation:
    def test_intelligence_below_zero_raises(self):
        with pytest.raises(ValidationError):
            PersonaProfile(intelligence=-0.1)

    def test_intelligence_above_one_raises(self):
        with pytest.raises(ValidationError):
            PersonaProfile(intelligence=1.1)

    def test_intelligence_at_zero_is_valid(self):
        p = PersonaProfile(intelligence=0.0)
        assert p.intelligence == 0.0

    def test_intelligence_at_one_is_valid(self):
        p = PersonaProfile(intelligence=1.0)
        assert p.intelligence == 1.0

    def test_memory_below_zero_raises(self):
        with pytest.raises(ValidationError):
            PersonaProfile(memory=-0.01)

    def test_memory_above_one_raises(self):
        with pytest.raises(ValidationError):
            PersonaProfile(memory=1.01)

    def test_experience_below_zero_raises(self):
        with pytest.raises(ValidationError):
            PersonaProfile(experience=-0.5)

    def test_experience_above_one_raises(self):
        with pytest.raises(ValidationError):
            PersonaProfile(experience=2.0)

    def test_rhetoric_out_of_range_raises(self):
        with pytest.raises(ValidationError):
            PersonaProfile(rhetoric=1.5)

    def test_risk_appetite_out_of_range_raises(self):
        with pytest.raises(ValidationError):
            PersonaProfile(risk_appetite=-1.0)

    def test_discipline_out_of_range_raises(self):
        with pytest.raises(ValidationError):
            PersonaProfile(discipline=99)

    def test_empty_model_name_raises(self):
        with pytest.raises(ValidationError):
            PersonaProfile(model="")

    def test_context_window_below_512_raises(self):
        with pytest.raises(ValidationError):
            PersonaProfile(context_window=256)

    def test_reasoning_budget_below_64_raises(self):
        with pytest.raises(ValidationError):
            PersonaProfile(reasoning_budget=32)


class TestPersonaProfileCustom:
    def test_full_custom_profile(self):
        p = PersonaProfile(
            intelligence=0.9,
            memory=0.8,
            experience=0.3,
            rhetoric=0.7,
            risk_appetite=0.6,
            discipline=0.4,
            model="qwen-max",
            context_window=32768,
            reasoning_budget=4096,
        )
        assert p.intelligence == 0.9
        assert p.memory == 0.8
        assert p.experience == 0.3
        assert p.rhetoric == 0.7
        assert p.risk_appetite == 0.6
        assert p.discipline == 0.4
        assert p.model == "qwen-max"
        assert p.context_window == 32768
        assert p.reasoning_budget == 4096

    def test_serializes_to_dict(self):
        p = PersonaProfile(intelligence=0.8, model="qwen-turbo")
        d = p.model_dump()
        assert d["intelligence"] == 0.8
        assert d["model"] == "qwen-turbo"
