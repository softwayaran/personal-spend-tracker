"""Tests for the safety warning when test.db exists."""

import argparse
from unittest.mock import patch

from budget_parser.cli.extract import extract_main
from budget_parser.cli.categorize import categorize_main


def test_extract_warns_when_test_db_exists(tmp_path, capsys):
    test_db = tmp_path / "test.db"
    test_db.touch()

    args = argparse.Namespace(
        year=2025,
        config=None,
        db="budget.db",
        test=False,
        todo_folder=None,
        done_folder=None,
        log_level=None,
        no_move=False,
    )
    with patch("budget_parser.cli.extract.Pipeline") as mock_pipeline, \
         patch("budget_parser.cli.extract.init_db"), \
         patch("budget_parser.cli.extract.Path.cwd", return_value=tmp_path):
        mock_pipeline.return_value.run.return_value = []
        extract_main(args)

    captured = capsys.readouterr()
    assert "test.db exists" in captured.err
    assert "--test" in captured.err


def test_extract_no_warning_when_test_db_absent(tmp_path, capsys):
    args = argparse.Namespace(
        year=2025,
        config=None,
        db="budget.db",
        test=False,
        todo_folder=None,
        done_folder=None,
        log_level=None,
        no_move=False,
    )
    with patch("budget_parser.cli.extract.Pipeline") as mock_pipeline, \
         patch("budget_parser.cli.extract.init_db"), \
         patch("budget_parser.cli.extract.Path.cwd", return_value=tmp_path):
        mock_pipeline.return_value.run.return_value = []
        extract_main(args)

    captured = capsys.readouterr()
    assert "test.db exists" not in captured.err


def test_extract_no_warning_with_test_flag(tmp_path, capsys):
    test_db = tmp_path / "test.db"
    test_db.touch()

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
         patch("budget_parser.cli.extract.init_db"), \
         patch("budget_parser.cli.extract.Path.cwd", return_value=tmp_path):
        mock_pipeline.return_value.run.return_value = []
        extract_main(args)

    captured = capsys.readouterr()
    assert "test.db exists" not in captured.err


def test_extract_no_warning_with_explicit_db(tmp_path, capsys):
    test_db = tmp_path / "test.db"
    test_db.touch()

    args = argparse.Namespace(
        year=2025,
        config=None,
        db="custom.db",
        test=False,
        todo_folder=None,
        done_folder=None,
        log_level=None,
        no_move=False,
    )
    with patch("budget_parser.cli.extract.Pipeline") as mock_pipeline, \
         patch("budget_parser.cli.extract.init_db"), \
         patch("budget_parser.cli.extract.Path.cwd", return_value=tmp_path):
        mock_pipeline.return_value.run.return_value = []
        extract_main(args)

    captured = capsys.readouterr()
    assert "test.db exists" not in captured.err


def test_categorize_warns_when_test_db_exists(tmp_path, capsys):
    test_db = tmp_path / "test.db"
    test_db.touch()

    args = argparse.Namespace(
        year=2025,
        config=None,
        db="budget.db",
        test=False,
        log_level="INFO",
        no_enrich=True,
    )
    with patch("budget_parser.cli.categorize.init_db"), \
         patch("budget_parser.cli.categorize.get_categories", return_value=[]), \
         patch("budget_parser.cli.categorize.get_regex_rules", return_value=[]), \
         patch("budget_parser.cli.categorize.Path.cwd", return_value=tmp_path):
        categorize_main(args)

    captured = capsys.readouterr()
    assert "test.db exists" in captured.err
    assert "--test" in captured.err


def test_categorize_no_warning_with_test_flag(tmp_path, capsys):
    test_db = tmp_path / "test.db"
    test_db.touch()

    args = argparse.Namespace(
        year=2025,
        config=None,
        db="budget.db",
        test=True,
        log_level="INFO",
        no_enrich=True,
    )
    with patch("budget_parser.cli.categorize.init_db"), \
         patch("budget_parser.cli.categorize.get_categories", return_value=[]), \
         patch("budget_parser.cli.categorize.get_regex_rules", return_value=[]), \
         patch("budget_parser.cli.categorize.Path.cwd", return_value=tmp_path):
        categorize_main(args)

    captured = capsys.readouterr()
    assert "test.db exists" not in captured.err
