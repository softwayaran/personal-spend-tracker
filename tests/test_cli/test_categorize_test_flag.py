"""Tests for the --test flag on the categorize CLI."""

import argparse
from unittest.mock import patch

from budget_parser.cli.categorize import add_parser, categorize_main


def _parse_categorize_args(args: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers()
    add_parser(subs)
    return parser.parse_args(["categorize"] + args)


def test_default_db_is_budget_db():
    ns = _parse_categorize_args(["--year", "2025"])
    assert ns.db == "budget.db"
    assert ns.test is False


def test_test_flag_present():
    ns = _parse_categorize_args(["--year", "2025", "--test"])
    assert ns.test is True


def test_explicit_db_with_test_flag():
    ns = _parse_categorize_args(["--year", "2025", "--test", "--db", "custom.db"])
    assert ns.db == "custom.db"
    assert ns.test is True


def test_categorize_main_test_flag_sets_db_path():
    args = argparse.Namespace(
        year=2025,
        config=None,
        db="budget.db",
        test=True,
        log_level="INFO",
        no_enrich=True,
    )
    with patch("budget_parser.cli.categorize.init_db") as mock_init, \
         patch("budget_parser.cli.categorize.auto_populate_category_descriptions", return_value=0), \
         patch("budget_parser.cli.categorize.get_categories", return_value=[]), \
         patch("budget_parser.cli.categorize.get_regex_rules", return_value=[]), \
         patch("budget_parser.cli.categorize.get_uncategorized_transactions", return_value=[]):
        categorize_main(args)
        mock_init.assert_called_once_with("test.db")


def test_categorize_main_explicit_db_wins():
    args = argparse.Namespace(
        year=2025,
        config=None,
        db="custom.db",
        test=True,
        log_level="INFO",
        no_enrich=True,
    )
    with patch("budget_parser.cli.categorize.init_db") as mock_init, \
         patch("budget_parser.cli.categorize.auto_populate_category_descriptions", return_value=0), \
         patch("budget_parser.cli.categorize.get_categories", return_value=[]), \
         patch("budget_parser.cli.categorize.get_regex_rules", return_value=[]), \
         patch("budget_parser.cli.categorize.get_uncategorized_transactions", return_value=[]):
        categorize_main(args)
        mock_init.assert_called_once_with("custom.db")
