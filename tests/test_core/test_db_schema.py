"""Tests for schema migration — new columns on transactions and categories."""

import sqlite3
import pytest
from budget_parser.database.db import init_db, get_connection


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test_budget.db")
    init_db(path)
    return path


class TestSchemaMigration:
    def test_transactions_has_confidence_column(self, db_path):
        conn = get_connection(db_path)
        try:
            row = conn.execute(
                "SELECT confidence FROM transactions LIMIT 1"
            ).fetchone()
        except sqlite3.OperationalError:
            pytest.fail("transactions table missing 'confidence' column")
        finally:
            conn.close()

    def test_transactions_has_categorized_by_column(self, db_path):
        conn = get_connection(db_path)
        try:
            row = conn.execute(
                "SELECT categorized_by FROM transactions LIMIT 1"
            ).fetchone()
        except sqlite3.OperationalError:
            pytest.fail("transactions table missing 'categorized_by' column")
        finally:
            conn.close()

    def test_categories_has_description_column(self, db_path):
        conn = get_connection(db_path)
        try:
            row = conn.execute(
                "SELECT description FROM categories LIMIT 1"
            ).fetchone()
        except sqlite3.OperationalError:
            pytest.fail("categories table missing 'description' column")
        finally:
            conn.close()

    def test_init_db_idempotent_with_new_columns(self, db_path):
        """Calling init_db twice should not error."""
        init_db(db_path)
        conn = get_connection(db_path)
        try:
            conn.execute("SELECT confidence, categorized_by FROM transactions LIMIT 1")
            conn.execute("SELECT description FROM categories LIMIT 1")
        except sqlite3.OperationalError as e:
            pytest.fail(f"Second init_db broke schema: {e}")
        finally:
            conn.close()

    def test_migration_adds_columns_to_existing_db(self, tmp_path):
        """Simulate an old DB without the new columns, then run init_db."""
        path = str(tmp_path / "old.db")
        conn = sqlite3.connect(path)
        conn.executescript("""
            CREATE TABLE categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                sub_category TEXT NOT NULL,
                UNIQUE(category, sub_category)
            );
            CREATE TABLE transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                year INTEGER NOT NULL,
                date TEXT NOT NULL,
                description TEXT NOT NULL,
                amount REAL NOT NULL,
                category TEXT NOT NULL DEFAULT '',
                sub_category TEXT NOT NULL DEFAULT '',
                merchant TEXT NOT NULL DEFAULT '',
                UNIQUE(year, date, description, amount)
            );
        """)
        conn.close()

        init_db(path)

        conn = sqlite3.connect(path)
        conn.execute("SELECT confidence, categorized_by FROM transactions LIMIT 1")
        conn.execute("SELECT description FROM categories LIMIT 1")
        conn.close()
