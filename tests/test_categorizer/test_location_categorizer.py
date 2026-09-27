"""Tests for LocationCategorizer."""

import pytest

from budget_parser.categorizer.location_categorizer import LocationCategorizer


class TestStateExtraction:
    """Test _extract_state method."""

    def test_trailing_state_with_space(self):
        cat = LocationCategorizer("MI")
        assert cat._extract_state("MCDONALD'S F40509 CEDAR CITY UT") == "UT"

    def test_glued_state(self):
        cat = LocationCategorizer("MI")
        assert cat._extract_state("MACYS WOODLANDKENTWOODMI $86.86") == "MI"

    def test_state_before_dollar(self):
        cat = LocationCategorizer("MI")
        assert cat._extract_state("CHICK-FIL-A#03896TOLEDOOH $35.83") == "OH"

    def test_state_before_negative_dollar(self):
        cat = LocationCategorizer("MI")
        assert cat._extract_state("WALMART.COM 8009256278BENTONVILLEAR - $38.13") == "AR"

    def test_canadian_province(self):
        cat = LocationCategorizer("MI")
        assert cat._extract_state("SHELL C81446 STRATHROY ON") == "ON"

    def test_dc(self):
        cat = LocationCategorizer("MI")
        assert cat._extract_state("NATIONALMALLPARKINGWASHINGTONDC") == "DC"

    def test_no_state(self):
        cat = LocationCategorizer("MI")
        assert cat._extract_state("Association Fee") is None

    def test_no_state_short_string(self):
        cat = LocationCategorizer("MI")
        assert cat._extract_state("Mummy") is None

    def test_hk_not_a_state(self):
        cat = LocationCategorizer("MI")
        assert cat._extract_state("Ant*MoboreaderHongKongChinaHK") is None


class TestOnlineExclusion:
    """Test that online transactions are skipped."""

    def test_dotcom_skipped(self):
        cat = LocationCategorizer("MI")
        txs = [{"description": "WALMART.COM 8009256278BENTONVILLEAR $64.95", "category": ""}]
        result = cat.categorize(txs)
        assert result[0]["category"] == ""

    def test_www_skipped(self):
        cat = LocationCategorizer("MI")
        txs = [{"description": "WWW.KOHLS.COM #0873MIDDLETOWNOH $60.39", "category": ""}]
        result = cat.categorize(txs)
        assert result[0]["category"] == ""

    def test_bill_skipped(self):
        cat = LocationCategorizer("MI")
        txs = [{"description": "AMAZONMKTPL*OQ2KH9SN3Amzn.com/billWA", "category": ""}]
        result = cat.categorize(txs)
        assert result[0]["category"] == ""

    def test_online_skipped(self):
        cat = LocationCategorizer("MI")
        txs = [{"description": "AMC 9640 ONLINE 888-440-4262 KS", "category": ""}]
        result = cat.categorize(txs)
        assert result[0]["category"] == ""


class TestCategorize:
    """Test full categorize method."""

    def test_out_of_state_becomes_vacation(self):
        cat = LocationCategorizer("MI")
        txs = [{"description": "MCDONALD'S F40509 CEDAR CITY UT", "category": ""}]
        result = cat.categorize(txs)
        assert result[0]["category"] == "Vacation"
        assert result[0]["sub_category"] == ""
        assert result[0]["confidence"] == 0.9
        assert result[0]["categorized_by"] == "location"

    def test_home_state_skipped(self):
        cat = LocationCategorizer("MI")
        txs = [{"description": "MEIJER STORE #158 GRAND RAPIDS MI", "category": ""}]
        result = cat.categorize(txs)
        assert result[0]["category"] == ""

    def test_already_categorized_skipped(self):
        cat = LocationCategorizer("MI")
        txs = [{"description": "SHELL C81446 STRATHROY ON", "category": "Car", "sub_category": "Gas"}]
        result = cat.categorize(txs)
        assert result[0]["category"] == "Car"

    def test_no_state_skipped(self):
        cat = LocationCategorizer("MI")
        txs = [{"description": "Association Fee", "category": ""}]
        result = cat.categorize(txs)
        assert result[0]["category"] == ""

    def test_mixed_batch(self):
        cat = LocationCategorizer("MI")
        txs = [
            {"description": "SHAKE SHACK LAS LAS VEGAS NV", "category": ""},
            {"description": "MEIJER STORE GRAND RAPIDS MI", "category": ""},
            {"description": "BRYCE CANYON NATL PARK UT", "category": ""},
            {"description": "Association Fee", "category": ""},
        ]
        result = cat.categorize(txs)
        assert result[0]["category"] == "Vacation"
        assert result[1]["category"] == ""
        assert result[2]["category"] == "Vacation"
        assert result[3]["category"] == ""

    def test_empty_home_state_skips_all(self):
        cat = LocationCategorizer("")
        txs = [{"description": "MCDONALD'S F40509 CEDAR CITY UT", "category": ""}]
        result = cat.categorize(txs)
        assert result[0]["category"] == ""
