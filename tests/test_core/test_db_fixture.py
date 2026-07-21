"""Verify the db_path fixture provides a working isolated database."""

from pathlib import Path

from budget_parser.database.db import get_connection, upsert_transactions, get_transactions


def test_db_path_fixture_creates_initialized_db(db_path):
    """Fixture should return a path to an existing, initialized SQLite DB."""
    assert Path(db_path).exists()
    conn = get_connection(db_path)
    try:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = sorted(r[0] for r in tables)
        assert "categories" in table_names
        assert "transactions" in table_names
        assert "regex_rules" in table_names
        assert "merchant_cache" in table_names
    finally:
        conn.close()


def test_db_path_fixture_is_isolated(db_path):
    """Each test should get its own empty DB — no data from other tests."""
    txs = get_transactions(db_path, 2025)
    assert txs == []


def test_db_path_fixture_is_writable(db_path):
    """Fixture DB should support normal read/write operations."""
    upsert_transactions(db_path, 2025, [
        {"date": "01/15", "description": "TEST STORE", "amount": 42.00},
    ])
    txs = get_transactions(db_path, 2025)
    assert len(txs) == 1
    assert txs[0]["description"] == "TEST STORE"
