"""Tests for regex-based merchant name extraction."""

import pytest

from budget_parser.categorizer.merchant_extractor import MerchantExtractor


@pytest.fixture
def extractor():
    return MerchantExtractor()


class TestMerchantExtractor:
    def test_strips_store_number(self, extractor):
        assert extractor.extract("KROGER #512 SPRINGFIELD IL") == "Kroger"

    def test_strips_sq_prefix(self, extractor):
        assert extractor.extract("SQ *BLUE BOTTLE COFFEE") == "Blue Bottle Coffee"

    def test_strips_phone_and_state(self, extractor):
        assert extractor.extract("NETFLIX.COM408-5403700CA") == "Netflix"

    def test_strips_tst_prefix(self, extractor):
        assert extractor.extract("TST* THAI FUSION GRAND RAPIDS MI") == "Thai Fusion"

    def test_strips_pp_prefix(self, extractor):
        assert extractor.extract("PP*SPOTIFY") == "Spotify"

    def test_strips_paypal_prefix(self, extractor):
        assert extractor.extract("PAYPAL *UBER EATS") == "Uber Eats"

    def test_strips_location_city_state(self, extractor):
        assert extractor.extract("OLIVE GARDEN #1234 SPRINGFIELD IL") == "Olive Garden"

    def test_strips_zip_code(self, extractor):
        assert extractor.extract("TARGET STORE DETROIT MI 48226") == "Target Store"

    def test_handles_simple_name(self, extractor):
        assert extractor.extract("AMAZON") == "Amazon"

    def test_empty_string(self, extractor):
        assert extractor.extract("") == ""

    def test_whitespace_only(self, extractor):
        assert extractor.extract("   ") == ""

    def test_preserves_multi_word_merchants(self, extractor):
        result = extractor.extract("WHOLE FOODS MARKET")
        assert result == "Whole Foods Market"
