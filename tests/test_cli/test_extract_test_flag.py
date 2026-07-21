"""Tests for the --test flag on the extract CLI."""

import argparse
from unittest.mock import patch

from budget_parser.cli.extract import add_parser, extract_main


def _parse_extract_args(args: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers()
    add_parser(subs)
    return parser.parse_args(["extract"] + args)


def test_default_db_is_budget_db():
    ns = _parse_extract_args(["--year", "2025"])
    assert ns.db == "budget.db"
    assert ns.test is False


def test_test_flag_sets_test_db():
    ns = _parse_extract_args(["--year", "2025", "--test"])
    assert ns.test is True


def test_explicit_db_with_test_flag():
    ns = _parse_extract_args(["--year", "2025", "--test", "--db", "custom.db"])
    assert ns.db == "custom.db"
    assert ns.test is True


def test_extract_main_test_flag_sets_db_path():
    args = argparse.Namespace(
        year=2025,
        config=None,
        db="budget.db",
        test=True,
        todo_folder=None,
        done_folder=None,
        log_level=None,
        no_move=False,
    )
    with patch("budget_parser.cli.extract.Pipeline") as mock_pipeline, \
         patch("budget_parser.cli.extract.init_db"):
        mock_pipeline.return_value.run.return_value = []
        extract_main(args)
        _, kwargs = mock_pipeline.call_args
        assert kwargs["db_path"] == "test.db"


def test_extract_main_test_flag_explicit_db_wins():
    args = argparse.Namespace(
        year=2025,
        config=None,
        db="custom.db",
        test=True,
        todo_folder=None,
        done_folder=None,
        log_level=None,
        no_move=False,
    )
    with patch("budget_parser.cli.extract.Pipeline") as mock_pipeline, \
         patch("budget_parser.cli.extract.init_db"):
        mock_pipeline.return_value.run.return_value = []
        extract_main(args)
        _, kwargs = mock_pipeline.call_args
        assert kwargs["db_path"] == "custom.db"


def test_extract_main_test_flag_disables_move():
    args = argparse.Namespace(
        year=2025,
        config=None,
        db="budget.db",
        test=True,
        todo_folder=None,
        done_folder=None,
        log_level=None,
        no_move=False,
    )
    with patch("budget_parser.cli.extract.Pipeline") as mock_pipeline, \
         patch("budget_parser.cli.extract.init_db"):
        mock_pipeline.return_value.run.return_value = []
        extract_main(args)
        assert args.no_move is True
