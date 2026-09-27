"""Tests for the four-tier categorization pipeline wiring."""

import sys
from unittest.mock import patch, MagicMock

import pytest

# laya is not installed in this environment yet (installed in a later task).
# Register a stand-in module in sys.modules before importing anything that
# transitively imports laya (budget_parser.cli.categorize ->
# budget_parser.categorizer.laya_categorizer -> `from laya import Router`).
if "laya" not in sys.modules:
    sys.modules["laya"] = MagicMock()

from budget_parser.database.db import (
    init_db, add_category, upsert_transactions, get_transactions,
)


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    add_category(path, "Grocery", "Grocery", "grocery stores")
    add_category(path, "Restaurants", "Family", "family restaurants")
    upsert_transactions(path, 2026, [
        {"date": "2026-01-15", "description": "KROGER #512 SPRINGFIELD IL", "amount": 55.00},
        {"date": "2026-01-16", "description": "AMBIGUOUS THING", "amount": 12.00},
    ])
    return path


class TestCategorizePipelineLaya:
    @patch("budget_parser.cli.categorize.CategorizationAgent")
    @patch("budget_parser.cli.categorize.WebEnricher")
    @patch("budget_parser.cli.categorize.LayaCategorizer")
    def test_laya_accepted_skips_llm(self, mock_laya_cls, mock_enricher_cls, mock_agent_cls, db_path):
        """When laya accepts all transactions, LLM should not be called."""
        mock_laya = MagicMock()
        mock_laya.categorize.return_value = [
            {
                "id": 1, "description": "KROGER #512", "category": "Grocery",
                "sub_category": "Grocery", "confidence": 0.9, "categorized_by": "laya",
                "amount": 55.00,
            },
            {
                "id": 2, "description": "AMBIGUOUS THING", "category": "Restaurants",
                "sub_category": "Family", "confidence": 0.85, "categorized_by": "laya",
                "amount": 12.00,
            },
        ]
        mock_laya_cls.return_value = mock_laya

        from budget_parser.cli.categorize import categorize_main
        from argparse import Namespace

        args = Namespace(
            config=None, db=db_path, log_level="WARNING", no_enrich=True,
            year=2026, test=False,
        )
        categorize_main(args)

        mock_agent_cls.return_value.categorize.assert_not_called()

    @patch("budget_parser.cli.categorize.CategorizationAgent")
    @patch("budget_parser.cli.categorize.WebEnricher")
    @patch("budget_parser.cli.categorize.LayaCategorizer")
    def test_low_confidence_falls_through_to_llm(self, mock_laya_cls, mock_enricher_cls, mock_agent_cls, db_path):
        """Low-confidence laya results should route to LLM fallback."""
        mock_laya = MagicMock()
        mock_laya.categorize.return_value = [
            {
                "id": 1, "description": "KROGER #512", "category": "Grocery",
                "sub_category": "Grocery", "confidence": 0.9, "categorized_by": "laya",
                "amount": 55.00,
            },
            {
                "id": 2, "description": "AMBIGUOUS THING", "category": "",
                "amount": 12.00,
                "_laya_best_guess": {"category": "Restaurants", "sub_category": "Family", "confidence": 0.4},
            },
        ]
        mock_laya_cls.return_value = mock_laya

        mock_agent = MagicMock()
        mock_agent.categorize.return_value = [
            {
                "id": 2, "description": "AMBIGUOUS THING", "category": "Restaurants",
                "sub_category": "Family", "merchant": "Ambiguous",
                "amount": 12.00,
            },
        ]
        mock_agent_cls.return_value = mock_agent

        from budget_parser.cli.categorize import categorize_main
        from argparse import Namespace

        args = Namespace(
            config=None, db=db_path, log_level="WARNING", no_enrich=True,
            year=2026, test=False,
        )
        categorize_main(args)

        mock_agent.categorize.assert_called_once()
        call_txs = mock_agent.categorize.call_args[0][0]
        assert len(call_txs) == 1
        assert call_txs[0]["id"] == 2
