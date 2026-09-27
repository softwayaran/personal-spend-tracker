"""Tests for laya-related settings fields."""

from budget_parser.config.settings import Settings, reset_settings, get_settings


class TestLayaSettings:
    def test_defaults(self):
        reset_settings()
        s = Settings()
        assert s.laya_model == "convaiinnovations/laya"
        assert s.laya_confidence_threshold == 0.6
        assert s.laya_enabled is True

    def test_override(self):
        reset_settings()
        s = Settings(laya_enabled=False, laya_confidence_threshold=0.8)
        assert s.laya_enabled is False
        assert s.laya_confidence_threshold == 0.8

    def test_threshold_bounds(self):
        reset_settings()
        s = Settings(laya_confidence_threshold=0.0)
        assert s.laya_confidence_threshold == 0.0
        s = Settings(laya_confidence_threshold=1.0)
        assert s.laya_confidence_threshold == 1.0


def test_home_state_default(tmp_path):
    """home_state defaults to MI."""
    config = tmp_path / "config.yaml"
    config.write_text("llm_model: llama3\n")
    reset_settings()
    s = get_settings(config)
    assert s.home_state == "MI"


def test_home_state_override(tmp_path):
    """home_state can be overridden in config."""
    config = tmp_path / "config.yaml"
    config.write_text("home_state: OH\n")
    reset_settings()
    s = get_settings(config)
    assert s.home_state == "OH"
