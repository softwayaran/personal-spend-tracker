"""Tests for TransactionValidator date handling."""

from budget_parser.validators.transaction_validator import TransactionValidator


def test_validator_accepts_month_name_dates():
    validator = TransactionValidator()
    source = "January 22 NETFLIX.COM 15.99"
    raw = [{"date": "January 22", "description": "NETFLIX.COM", "amount": 15.99}]

    validated = validator.validate(raw, source)

    assert len(validated) == 1
    assert validated[0].date == "01/22"


def test_validator_rejects_unknown_date_format():
    validator = TransactionValidator()
    source = "Foo 22 NETFLIX.COM 15.99"
    raw = [{"date": "Foo 22", "description": "NETFLIX.COM", "amount": 15.99}]

    validated = validator.validate(raw, source)

    assert validated == []
