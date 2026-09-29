"""Tests for laya two-step categorizer with mocked laya calls."""

import sys
from unittest.mock import MagicMock, patch

import pytest

# laya is not installed in this environment yet (installed in a later task).
# Register a stand-in module in sys.modules so `from laya import Router`
# succeeds at import time; individual tests then patch the `Router` name
# directly. NOTE: this intentionally does not use `patch.dict` here — that
# context manager wipes sys.modules back to its pre-`with` snapshot on exit,
# which would also unregister every submodule imported inside the block
# (e.g. budget_parser.categorizer.laya_categorizer itself), breaking later
# `@patch("budget_parser.categorizer.laya_categorizer.Router")` lookups.
sys.modules.setdefault("laya", MagicMock())

from budget_parser.categorizer.laya_categorizer import LayaCategorizer  # noqa: E402


@pytest.fixture
def categories():
    return [
        {"category": "Grocery", "sub_category": "Grocery", "description": "grocery stores, supermarkets"},
        {"category": "Grocery", "sub_category": "Indian", "description": "Indian grocery stores"},
        {"category": "Restaurants", "sub_category": "Family", "description": "family restaurants"},
        {"category": "Restaurants", "sub_category": "Office", "description": "work lunches"},
        {"category": "Car", "sub_category": "Gas", "description": "gas stations, fuel"},
    ]


def _mock_predict(responses):
    """Create a mock router whose predict() returns responses in order."""
    mock_router = MagicMock()
    mock_router.predict = MagicMock(side_effect=responses)
    return mock_router


class TestLayaCategorizer:
    @patch("budget_parser.categorizer.laya_categorizer.Router")
    def test_high_confidence_categorization(self, mock_router_cls, categories):
        mock_router = MagicMock()
        mock_router.predict.side_effect = [
            # Step 1: category choice
            {"answers": {"category": {"choice": "Grocery", "confidence": 0.92, "distribution": {}}}},
            # Step 2: sub_category choice
            {"answers": {"sub_category": {"choice": "Grocery", "confidence": 0.88, "distribution": {}}}},
        ]
        mock_router_cls.return_value = mock_router

        cat = LayaCategorizer(categories, model="convaiinnovations/laya", confidence_threshold=0.6)
        transactions = [{"id": 1, "description": "KROGER #512 SPRINGFIELD IL", "category": ""}]
        result = cat.categorize(transactions)

        assert result[0]["category"] == "Grocery"
        assert result[0]["sub_category"] == "Grocery"
        assert result[0]["confidence"] == 0.88  # min(0.92, 0.88)
        assert result[0]["categorized_by"] == "laya"

    @patch("budget_parser.categorizer.laya_categorizer.Router")
    def test_low_confidence_skipped(self, mock_router_cls, categories):
        mock_router = MagicMock()
        mock_router.predict.side_effect = [
            {"answers": {"category": {"choice": "Car", "confidence": 0.45, "distribution": {}}}},
            {"answers": {"sub_category": {"choice": "Gas", "confidence": 0.90, "distribution": {}}}},
        ]
        mock_router_cls.return_value = mock_router

        cat = LayaCategorizer(categories, model="convaiinnovations/laya", confidence_threshold=0.6)
        transactions = [{"id": 1, "description": "AMBIGUOUS MERCHANT", "category": ""}]
        result = cat.categorize(transactions)

        assert result[0]["category"] == ""
        assert result[0].get("_laya_best_guess") == {
            "category": "Car", "sub_category": "Gas", "confidence": 0.45,
        }

    @patch("budget_parser.categorizer.laya_categorizer.Router")
    def test_skips_already_categorized(self, mock_router_cls, categories):
        mock_router = MagicMock()
        mock_router_cls.return_value = mock_router

        cat = LayaCategorizer(categories, model="convaiinnovations/laya", confidence_threshold=0.6)
        transactions = [{"id": 1, "description": "NETFLIX", "category": "Utilities"}]
        result = cat.categorize(transactions)

        assert result[0]["category"] == "Utilities"
        mock_router.predict.assert_not_called()

    @patch("budget_parser.categorizer.laya_categorizer.Router")
    def test_builds_category_criteria_from_descriptions(self, mock_router_cls, categories):
        mock_router = MagicMock()
        mock_router.predict.side_effect = [
            {"answers": {"category": {"choice": "Grocery", "confidence": 0.95, "distribution": {}}}},
            {"answers": {"sub_category": {"choice": "Indian", "confidence": 0.80, "distribution": {}}}},
        ]
        mock_router_cls.return_value = mock_router

        cat = LayaCategorizer(categories, model="convaiinnovations/laya", confidence_threshold=0.6)
        criteria = cat._category_criteria
        assert "Grocery" in criteria
        assert "Restaurants" in criteria
        assert "Car" in criteria

    @patch("budget_parser.categorizer.laya_categorizer.Router")
    def test_handles_laya_exception(self, mock_router_cls, categories):
        mock_router = MagicMock()
        mock_router.predict.side_effect = RuntimeError("model not loaded")
        mock_router_cls.return_value = mock_router

        cat = LayaCategorizer(categories, model="convaiinnovations/laya", confidence_threshold=0.6)
        transactions = [{"id": 1, "description": "KROGER", "category": ""}]
        result = cat.categorize(transactions)

        assert result[0]["category"] == ""
