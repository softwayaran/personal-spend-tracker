"""Tests for laya-related settings fields."""

from budget_parser.config.settings import Settings, reset_settings


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
