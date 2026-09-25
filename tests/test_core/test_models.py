"""Tests for core data models."""

import pytest
from pydantic import ValidationError

from budget_parser.core.models import Transaction


class TestTransaction:
    """Tests for Transaction model."""

    def test_valid_transaction(self):
        """Test creating a valid transaction."""
        trans = Transaction(
            date="11/07",
            description="MEIJER STORE #158",
            amount=113.76
        )

        assert trans.date == "11/07"
        assert trans.description == "MEIJER STORE #158"
        assert trans.amount == 113.76

    def test_date_validation_valid_formats(self):
        """Test various valid date formats."""
        valid_dates = {
            "1/1": "01/01",
            "01/01": "01/01",
            "12/31": "12/31",
            "11/07/23": "11/07",
            "11/07/2023": "11/07",
            "Jan 22": "01/22",
            "January 22": "01/22",
            "Jan. 22, 2025": "01/22",
            "22 Jan": "01/22",
            "2025-01-22": "01/22",
        }

        for date, expected in valid_dates.items():
            trans = Transaction(date=date, description="Test", amount=10.0)
            assert trans.date == expected

    def test_date_validation_invalid_formats(self):
        """Test invalid date formats."""
        invalid_dates = ["Novembar 7", "13/07", "11/32", "abc"]

        for date in invalid_dates:
            with pytest.raises(ValidationError):
                Transaction(date=date, description="Test", amount=10.0)

    def test_description_validation(self):
        """Test description validation."""
        # Valid description
        trans = Transaction(date="11/07", description="Test Store", amount=10.0)
        assert trans.description == "Test Store"

        # Empty description should fail
        with pytest.raises(ValidationError):
            Transaction(date="11/07", description="", amount=10.0)

        # Whitespace-only description should fail
        with pytest.raises(ValidationError):
            Transaction(date="11/07", description="   ", amount=10.0)

    def test_amount_validation(self):
        """Test amount validation."""
        # Valid amounts
        trans1 = Transaction(date="11/07", description="Test", amount=100.50)
        assert trans1.amount == 100.50

        trans2 = Transaction(date="11/07", description="Test", amount=-50.00)
        assert trans2.amount == -50.00

        # String amount should be converted
        trans3 = Transaction(date="11/07", description="Test", amount="123.45")
        assert trans3.amount == 123.45

        # String with $ and commas should work
        trans4 = Transaction(date="11/07", description="Test", amount="$1,234.56")
        assert trans4.amount == 1234.56

        # Zero amount should fail
        with pytest.raises(ValidationError):
            Transaction(date="11/07", description="Test", amount=0)

    def test_model_dump(self):
        """Test conversion to dictionary via Pydantic model_dump."""
        trans = Transaction(date="11/07", description="Test Store", amount=100.50)
        trans_dict = trans.model_dump()

        assert trans_dict == {
            "date": "11/07",
            "description": "Test Store",
            "amount": 100.50
        }

    def test_model_validate(self):
        """Test creation from dictionary via Pydantic model_validate."""
        data = {
            "date": "11/07",
            "description": "Test Store",
            "amount": 100.50
        }

        trans = Transaction.model_validate(data)

        assert trans.date == "11/07"
        assert trans.description == "Test Store"
        assert trans.amount == 100.50
