"""Tests for KeywordFilter."""

import pytest
from budget_parser.filters.keyword_filter import KeywordFilter
from budget_parser.core.models import Transaction


class TestKeywordFilter:
    """Tests for KeywordFilter."""

    @pytest.fixture
    def filter(self):
        """Create a keyword filter with sample keywords."""
        keywords = ["points", "rewards", "cashback", "miles"]
        return KeywordFilter("RewardsFilter", keywords)

    def test_filter_removes_matching_transactions(self, filter):
        """Test that matching transactions are filtered out."""
        transactions = [
            Transaction(date="11/07", description="MEIJER STORE #158", amount=113.76),
            Transaction(date="11/08", description="REWARDS POINTS EARNED", amount=100.00),
            Transaction(date="11/10", description="AMAZON.COM", amount=45.99),
        ]

        filtered = filter.filter(transactions)

        assert len(filtered) == 2
        assert filtered[0].description == "MEIJER STORE #158"
        assert filtered[1].description == "AMAZON.COM"

    def test_filter_keeps_normal_transactions(self, filter):
        """Test that non-matching transactions are kept."""
        transactions = [
            Transaction(date="11/07", description="MEIJER STORE #158", amount=113.76),
            Transaction(date="11/10", description="AMAZON.COM", amount=45.99),
        ]

        filtered = filter.filter(transactions)

        assert len(filtered) == 2

    def test_filter_case_insensitive(self, filter):
        """Test that filtering is case-insensitive."""
        transactions = [
            Transaction(date="11/07", description="POINTS EARNED", amount=100.00),
            Transaction(date="11/08", description="points earned", amount=100.00),
            Transaction(date="11/09", description="Points Earned", amount=100.00),
        ]

        filtered = filter.filter(transactions)

        assert len(filtered) == 0

    def test_should_filter(self, filter):
        """Test should_filter method."""
        trans1 = Transaction(date="11/07", description="REWARDS POINTS", amount=100.00)
        trans2 = Transaction(date="11/08", description="MEIJER STORE", amount=50.00)

        assert filter.should_filter(trans1) is True
        assert filter.should_filter(trans2) is False

    def test_get_filter_name(self, filter):
        """Test get_filter_name returns the configured name."""
        assert filter.get_filter_name() == "RewardsFilter"

    def test_different_filter_names(self):
        """Test that KeywordFilter respects the name parameter."""
        f1 = KeywordFilter("PaymentFilter", ["autopay", "payment received"])
        f2 = KeywordFilter("AggregateFilter", ["total", "balance"])

        assert f1.get_filter_name() == "PaymentFilter"
        assert f2.get_filter_name() == "AggregateFilter"
