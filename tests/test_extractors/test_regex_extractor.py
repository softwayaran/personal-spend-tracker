"""Tests for RegexExtractor."""

import pytest
from budget_parser.extractors.regex_extractor import RegexExtractor


class TestRegexExtractor:
    """Tests for RegexExtractor."""

    @pytest.fixture
    def extractor(self):
        """Create a regex extractor."""
        return RegexExtractor()

    def test_extract_basic_transactions(self, extractor):
        """Test extraction of basic transactions."""
        chunk = """
11/07 MEIJER STORE #158 GRAND RAPIDS MI 113.76
11/08 SQ *FRIENDS OF THE LIBRAR Grand Rapids MI 2.00
11/10 AMAZON.COM AMZN.COM/BILL WA 45.99
"""

        transactions = extractor.extract(chunk)

        assert len(transactions) == 3
        assert transactions[0]["date"] == "11/07"
        assert "MEIJER" in transactions[0]["description"]
        assert transactions[0]["amount"] == 113.76

    def test_extract_with_dollar_signs(self, extractor):
        """Test extraction with dollar signs."""
        chunk = """
11/07 STORE NAME $113.76
11/08 ANOTHER STORE $2.00
"""

        transactions = extractor.extract(chunk)

        assert len(transactions) == 2
        assert transactions[0]["amount"] == 113.76
        assert transactions[1]["amount"] == 2.00

    def test_extract_negative_amounts(self, extractor):
        """Test extraction of negative amounts (credits/refunds)."""
        chunk = """
11/07 STORE NAME 113.76
11/08 REFUND FROM STORE -1955.00
"""

        transactions = extractor.extract(chunk)

        assert len(transactions) == 2
        assert transactions[0]["amount"] == 113.76
        assert transactions[1]["amount"] == -1955.00

    def test_extract_with_commas(self, extractor):
        """Test extraction of amounts with commas."""
        chunk = """
11/07 EXPENSIVE STORE 1,234.56
11/08 VERY EXPENSIVE 12,345.67
"""

        transactions = extractor.extract(chunk)

        assert len(transactions) == 2
        assert transactions[0]["amount"] == 1234.56
        assert transactions[1]["amount"] == 12345.67

    def test_skip_zero_amounts(self, extractor):
        """Test that zero amounts are skipped."""
        chunk = """
11/07 STORE NAME 0.00
11/08 ANOTHER STORE 100.00
"""

        transactions = extractor.extract(chunk)

        assert len(transactions) == 1
        assert transactions[0]["amount"] == 100.00

    def test_skip_short_descriptions(self, extractor):
        """Test that short descriptions (likely headers) are skipped."""
        chunk = """
11/07 AB 100.00
11/08 PROPER STORE NAME 200.00
"""

        transactions = extractor.extract(chunk)

        assert len(transactions) == 1
        assert "PROPER STORE NAME" in transactions[0]["description"]

    def test_skip_header_keywords(self, extractor):
        """Test that header keywords are skipped."""
        chunk = """
11/07 purchase 100.00
11/08 STORE NAME 200.00
11/09 total 300.00
"""

        transactions = extractor.extract(chunk)

        assert len(transactions) == 1
        assert "STORE NAME" in transactions[0]["description"]

    def test_extract_month_name_dates(self, extractor):
        """Test extraction when dates are month names."""
        chunk = """
January 22 NETFLIX.COM 15.99
Jan 23 STARBUCKS 8.50
"""

        transactions = extractor.extract(chunk)

        assert len(transactions) == 2
        assert transactions[0]["date"] == "January 22"
        assert transactions[1]["date"] == "Jan 23"
        assert transactions[0]["amount"] == 15.99
        assert transactions[1]["amount"] == 8.50
