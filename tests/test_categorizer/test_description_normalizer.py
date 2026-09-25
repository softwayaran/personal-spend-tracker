"""Tests for transaction description normalization."""

from budget_parser.categorizer.description_normalizer import normalize_description


def test_strips_trailing_alphanumeric_codes():
    assert normalize_description("AMZN MKTP US*2K7XY9Z0") == "AMZN MKTP US"


def test_removes_tst_prefix():
    assert normalize_description("TST* THAI FUSION") == "THAI FUSION"


def test_removes_sq_prefix():
    assert normalize_description("SQ *COFFEE SHOP") == "COFFEE SHOP"


def test_removes_pp_prefix():
    assert normalize_description("PP*SPOTIFY") == "SPOTIFY"


def test_strips_state_abbreviation_and_zip():
    assert normalize_description("MEIJER STORE #158 GRAND RAPIDS MI 49503") == "MEIJER STORE GRAND RAPIDS"


def test_strips_store_numbers():
    assert normalize_description("MEIJER STORE #158 GRAND RAPIDS") == "MEIJER STORE GRAND RAPIDS"


def test_strips_trailing_country_codes():
    assert normalize_description("Ant*StoryAppHongKongChinaHK") == "StoryApp"


def test_already_clean_description():
    assert normalize_description("NETFLIX") == "NETFLIX"


def test_removes_transaction_id_patterns():
    assert normalize_description("Netflix.com408-5403700CA") == "Netflix.com"


def test_empty_string():
    assert normalize_description("") == ""


def test_whitespace_collapsing():
    assert normalize_description("  SOME   MERCHANT   ") == "SOME MERCHANT"
