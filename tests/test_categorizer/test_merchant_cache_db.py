"""Tests for merchant_cache database operations."""

import os
import tempfile

import pytest

from budget_parser.database.db import (
    init_db,
    get_merchant_cache,
    upsert_merchant_cache,
)


@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    yield path
    os.unlink(path)


def test_cache_miss_returns_none(db_path):
    result = get_merchant_cache(db_path, "UNKNOWN MERCHANT")
    assert result is None


def test_upsert_and_retrieve(db_path):
    upsert_merchant_cache(db_path, "THAI FUSION", "Thai Fusion", "Thai restaurant")
    result = get_merchant_cache(db_path, "THAI FUSION")
    assert result is not None
    assert result["merchant_name"] == "Thai Fusion"
    assert result["business_type"] == "Thai restaurant"


def test_upsert_overwrites_existing(db_path):
    upsert_merchant_cache(db_path, "AMZN MKTP US", "Amazon", "online retail")
    upsert_merchant_cache(db_path, "AMZN MKTP US", "Amazon Marketplace", "online marketplace")
    result = get_merchant_cache(db_path, "AMZN MKTP US")
    assert result["merchant_name"] == "Amazon Marketplace"
    assert result["business_type"] == "online marketplace"


def test_no_result_entry(db_path):
    upsert_merchant_cache(db_path, "GIBBERISH123", "", "no_result")
    result = get_merchant_cache(db_path, "GIBBERISH123")
    assert result is not None
    assert result["business_type"] == "no_result"
