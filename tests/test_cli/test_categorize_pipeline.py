"""Tests for the four-tier categorization pipeline wiring."""

import argparse
import sys
from unittest.mock import patch, MagicMock

import pytest

# laya is not installed in this environment yet (installed in a later task).
# Register a stand-in module in sys.modules before importing anything that
# transitively imports laya (budget_parser.cli.categorize ->
# budget_parser.categorizer.laya_categorizer -> `from laya import Router`).
if "laya" not in sys.modules:
    sys.modules["laya"] = MagicMock()

from budget_parser.cli.categorize import categorize_main
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

        # Verify the LLM result persists in the DB, not the laya best guess
        final_txs = get_transactions(db_path, 2026)
        tx2 = [tx for tx in final_txs if tx["description"] == "AMBIGUOUS THING"][0]
        assert tx2["category"] == "Restaurants"
        assert tx2["categorized_by"] == "llm"

    @patch("budget_parser.cli.categorize.CategorizationAgent")
    @patch("budget_parser.cli.categorize.WebEnricher")
    @patch("budget_parser.cli.categorize.LayaCategorizer")
    def test_laya_disabled_skips_laya(self, mock_laya_cls, mock_enricher_cls, mock_agent_cls, db_path):
        """When laya_enabled=False, laya should not be instantiated."""
        mock_agent = MagicMock()
        mock_agent.categorize.return_value = [
            {
                "id": 1, "description": "KROGER #512 SPRINGFIELD IL", "category": "Grocery",
                "sub_category": "Grocery", "merchant": "Kroger", "amount": 55.00,
            },
            {
                "id": 2, "description": "AMBIGUOUS THING", "category": "Restaurants",
                "sub_category": "Family", "merchant": "Ambiguous", "amount": 12.00,
            },
        ]
        mock_agent_cls.return_value = mock_agent

        from budget_parser.cli.categorize import categorize_main
        from argparse import Namespace

        with patch("budget_parser.cli.categorize.get_settings") as mock_get_settings:
            mock_settings = MagicMock()
            mock_settings.laya_enabled = False
            mock_settings.web_enrichment_enabled = False
            mock_settings.llm_model = "test"
            mock_settings.llm_temperature = 0.1
            mock_settings.llm_top_p = 0.2
            mock_settings.llm_num_predict = 2000
            mock_settings.categorize_batch_size = 20
            mock_settings.log_file = None
            mock_settings.log_max_bytes = 1000000
            mock_settings.log_backup_count = 3
            mock_get_settings.return_value = mock_settings

            args = Namespace(
                config=None, db=db_path, log_level="WARNING", no_enrich=True,
                year=2026, test=False,
            )
            categorize_main(args)

        mock_laya_cls.assert_not_called()
        mock_agent.categorize.assert_called_once()


@patch("budget_parser.cli.categorize.auto_populate_category_descriptions")
@patch("budget_parser.cli.categorize.get_transactions")
@patch("budget_parser.cli.categorize.bulk_update_transaction_categories")
@patch("budget_parser.cli.categorize.get_uncategorized_transactions")
@patch("budget_parser.cli.categorize.get_regex_rules", return_value=[])
@patch("budget_parser.cli.categorize.get_categories", return_value=[
    {"category": "Restaurants", "sub_category": "Family", "description": "family dining"},
])
@patch("budget_parser.cli.categorize.init_db")
def test_location_categorizer_tags_vacation(
    mock_init, mock_cats, mock_rules, mock_uncat,
    mock_bulk, mock_txs, mock_auto, tmp_path
):
    """Out-of-state transaction is tagged as Vacation before laya."""
    mock_uncat.return_value = [
        {"id": 1, "description": "SHAKE SHACK LAS LAS VEGAS NV", "category": ""},
    ]
    mock_txs.return_value = []

    args = argparse.Namespace(
        year=2026, config=None, db=str(tmp_path / "test.db"),
        log_level="WARNING", no_enrich=True, test=False,
    )
    categorize_main(args)

    bulk_calls = mock_bulk.call_args_list
    location_call = bulk_calls[0]
    saved = location_call[0][1]
    assert any(tx["categorized_by"] == "location" and tx["category"] == "Vacation" for tx in saved)
