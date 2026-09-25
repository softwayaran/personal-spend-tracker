"""Tests for date parser helpers."""

from budget_parser.utils.date_parser import normalize_statement_date, parse_statement_date


def test_parse_statement_date_supported_formats():
    assert parse_statement_date("01/22") == (1, 22)
    assert parse_statement_date("1/22/2025") == (1, 22)
    assert parse_statement_date("2025-01-22") == (1, 22)
    assert parse_statement_date("January 22") == (1, 22)
    assert parse_statement_date("Jan 22") == (1, 22)
    assert parse_statement_date("Jan. 22, 2025") == (1, 22)
    assert parse_statement_date("22 Jan") == (1, 22)


def test_parse_statement_date_invalid_values():
    assert parse_statement_date("13/22") is None
    assert parse_statement_date("February 31") is None
    assert parse_statement_date("Not a date") is None


def test_normalize_statement_date():
    assert normalize_statement_date("January 22") == "01/22"
    assert normalize_statement_date("Jan 22") == "01/22"
    assert normalize_statement_date("1/2") == "01/02"
