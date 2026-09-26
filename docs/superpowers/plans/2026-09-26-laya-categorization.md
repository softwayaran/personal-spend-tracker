# Laya-Based Categorization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace LLM-based transaction categorization with laya System 1 classifier as the primary engine, keeping Ollama as a fallback for low-confidence results.

**Architecture:** Four-tier categorization waterfall: regex pre-pass → laya two-step classification → web enrichment + LLM fallback → flagged for review. Merchant names are extracted via regex instead of LLM. Confidence scores and categorization method are persisted in the DB and surfaced in the dashboard.

**Tech Stack:** Python 3.9+, laya >= 0.3.3, SQLite, Streamlit, Plotly, Ollama (fallback only)

## Global Constraints

- Python >= 3.9, all code must work on Windows (Git Bash + PowerShell)
- Activate venv before every shell command: `source myenv/Scripts/activate`
- Existing 70 tests must keep passing throughout
- `laya_enabled: false` must restore the old LLM-only behavior exactly
- No ORM — raw `sqlite3` through `budget_parser/database/db.py`
- Follow existing code patterns: flat functions in db.py, classes for categorizers, pydantic Settings

---

### Task 1: Database Schema — Add confidence, categorized_by, and category description columns

**Files:**
- Modify: `budget_parser/database/db.py:27-74` (init_db), `db.py:347-375` (bulk_update_transaction_categories)
- Modify: `budget_parser/database/db.py:81-89` (get_categories), `db.py:93-104` (add_category)
- Test: `tests/test_core/test_db_schema.py` (new)

**Interfaces:**
- Produces: `init_db(db_path)` now adds columns `confidence REAL`, `categorized_by TEXT` to transactions and `description TEXT` to categories. `bulk_update_transaction_categories(db_path, updates)` accepts optional `confidence` and `categorized_by` keys. `get_categories(db_path)` returns dicts with `description` key. `add_category(db_path, category, sub_category, description="")` accepts optional description.

- [ ] **Step 1: Write failing tests for schema migration**

Create `tests/test_core/test_db_schema.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source myenv/Scripts/activate && pytest tests/test_core/test_db_schema.py -v`
Expected: FAIL — columns don't exist yet.

- [ ] **Step 3: Update init_db to add new columns**

In `budget_parser/database/db.py`, update the `init_db` function. After the existing `conn.executescript(...)` block and `conn.commit()`, add column migration:

```python
def init_db(db_path: str) -> None:
    """Create tables if they don't exist. Idempotent — safe to call on every startup."""
    conn = get_connection(db_path)
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS categories (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                category     TEXT NOT NULL,
                sub_category TEXT NOT NULL,
                description  TEXT NOT NULL DEFAULT '',
                UNIQUE(category, sub_category)
            );

            CREATE TABLE IF NOT EXISTS regex_rules (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                priority     INTEGER NOT NULL DEFAULT 0,
                pattern      TEXT NOT NULL,
                category     TEXT NOT NULL,
                sub_category TEXT NOT NULL,
                merchant     TEXT NOT NULL DEFAULT '',
                enabled      INTEGER NOT NULL DEFAULT 1,
                UNIQUE(pattern)
            );

            CREATE TABLE IF NOT EXISTS transactions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                year            INTEGER NOT NULL,
                date            TEXT NOT NULL,
                description     TEXT NOT NULL,
                amount          REAL NOT NULL,
                category        TEXT NOT NULL DEFAULT '',
                sub_category    TEXT NOT NULL DEFAULT '',
                merchant        TEXT NOT NULL DEFAULT '',
                confidence      REAL,
                categorized_by  TEXT,
                UNIQUE(year, date, description, amount)
            );

            CREATE INDEX IF NOT EXISTS idx_transactions_year ON transactions(year);

            CREATE TABLE IF NOT EXISTS merchant_cache (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                description_pattern TEXT NOT NULL UNIQUE,
                merchant_name       TEXT NOT NULL DEFAULT '',
                business_type       TEXT NOT NULL DEFAULT '',
                created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()

        # Migrate existing DBs: add columns that may be missing
        _migrate_add_column(conn, "transactions", "confidence", "REAL")
        _migrate_add_column(conn, "transactions", "categorized_by", "TEXT")
        _migrate_add_column(conn, "categories", "description", "TEXT NOT NULL DEFAULT ''")
    finally:
        conn.close()


def _migrate_add_column(conn: sqlite3.Connection, table: str, column: str, col_type: str) -> None:
    """Add a column if it doesn't exist. Silently ignores duplicates."""
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # column already exists
```

Add `import sqlite3` to the existing imports if not already present (it is).

- [ ] **Step 4: Update bulk_update_transaction_categories to accept new fields**

In `budget_parser/database/db.py`, replace the existing `bulk_update_transaction_categories` function:

```python
def bulk_update_transaction_categories(db_path: str, updates: List[Dict]) -> int:
    """Update category/sub_category/merchant for a list of transactions by id.

    Each dict must have 'id'. Missing category fields default to empty string.
    Optionally accepts 'confidence' (float or None) and 'categorized_by' (str or None).
    Returns count of rows updated.
    """
    params = [
        (
            tx.get("category", ""),
            tx.get("sub_category", ""),
            tx.get("merchant", ""),
            tx.get("confidence"),
            tx.get("categorized_by"),
            tx["id"],
        )
        for tx in updates
        if tx.get("id") is not None
    ]
    if not params:
        return 0

    conn = get_connection(db_path)
    try:
        conn.executemany(
            """UPDATE transactions
               SET category = ?, sub_category = ?, merchant = ?,
                   confidence = ?, categorized_by = ?
               WHERE id = ?""",
            params,
        )
        conn.commit()
        return len(params)
    finally:
        conn.close()
```

- [ ] **Step 5: Update get_categories and add_category to include description**

In `budget_parser/database/db.py`, update `get_categories`:

```python
def get_categories(db_path: str) -> List[Dict]:
    """Return all categories ordered by category, sub_category."""
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT id, category, sub_category, description FROM categories ORDER BY category, sub_category"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
```

Update `add_category`:

```python
def add_category(db_path: str, category: str, sub_category: str, description: str = "") -> int:
    """Insert a new category/sub_category pair. Returns the new row id."""
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            "INSERT INTO categories (category, sub_category, description) VALUES (?, ?, ?)",
            (category, sub_category, description),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()
```

Update `get_transactions` and `get_uncategorized_transactions` to include the new columns:

```python
def get_transactions(db_path: str, year: int) -> List[Dict]:
    """Return all transactions for a year ordered by date."""
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """SELECT id, year, date, description, amount, category, sub_category,
                      merchant, confidence, categorized_by
               FROM transactions WHERE year = ? ORDER BY date""",
            (year,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_uncategorized_transactions(db_path: str, year: int) -> List[Dict]:
    """Return transactions with an empty category for a given year."""
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """SELECT id, year, date, description, amount, category, sub_category,
                      merchant, confidence, categorized_by
               FROM transactions WHERE year = ? AND category = '' ORDER BY date""",
            (year,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `source myenv/Scripts/activate && pytest tests/test_core/test_db_schema.py -v`
Expected: All 5 tests PASS.

Run: `source myenv/Scripts/activate && pytest --no-cov -q`
Expected: All existing tests still pass (72 total now).

- [ ] **Step 7: Commit**

```bash
git add budget_parser/database/db.py tests/test_core/test_db_schema.py
git commit -m "feat: add confidence, categorized_by, and category description columns

Add schema migration for new columns on transactions (confidence,
categorized_by) and categories (description). bulk_update now
accepts the new fields. Existing DBs are upgraded on init_db."
```

---

### Task 2: Settings — Add laya configuration fields

**Files:**
- Modify: `budget_parser/config/settings.py:76-88`
- Modify: `budget_parser/config/default_config.yaml`
- Test: `tests/test_core/test_settings_laya.py` (new)

**Interfaces:**
- Produces: `Settings.laya_model: str`, `Settings.laya_confidence_threshold: float`, `Settings.laya_enabled: bool`

- [ ] **Step 1: Write failing test**

Create `tests/test_core/test_settings_laya.py`:

```python
"""Tests for laya-related settings fields."""

from budget_parser.config.settings import Settings, reset_settings


class TestLayaSettings:
    def test_defaults(self):
        reset_settings()
        s = Settings()
        assert s.laya_model == "convaiinnovations/laya"
        assert s.laya_confidence_threshold == 0.6
        assert s.laya_enabled is True

    def test_override(self):
        reset_settings()
        s = Settings(laya_enabled=False, laya_confidence_threshold=0.8)
        assert s.laya_enabled is False
        assert s.laya_confidence_threshold == 0.8

    def test_threshold_bounds(self):
        reset_settings()
        s = Settings(laya_confidence_threshold=0.0)
        assert s.laya_confidence_threshold == 0.0
        s = Settings(laya_confidence_threshold=1.0)
        assert s.laya_confidence_threshold == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source myenv/Scripts/activate && pytest tests/test_core/test_settings_laya.py -v`
Expected: FAIL — fields don't exist.

- [ ] **Step 3: Add laya fields to Settings**

In `budget_parser/config/settings.py`, add after the web enrichment settings block (after line 88):

```python
    # Laya classification settings
    laya_model: str = Field(
        default="convaiinnovations/laya", description="HuggingFace laya checkpoint"
    )
    laya_confidence_threshold: float = Field(
        default=0.6, ge=0.0, le=1.0, description="Below this confidence, fall back to LLM"
    )
    laya_enabled: bool = Field(
        default=True, description="Use laya for categorization; false reverts to LLM-only"
    )
```

- [ ] **Step 4: Add laya settings to default_config.yaml**

Append to the end of `budget_parser/config/default_config.yaml`:

```yaml

# Laya classification settings
laya_model: "convaiinnovations/laya"          # HuggingFace checkpoint
laya_confidence_threshold: 0.6                # Below this -> LLM fallback
laya_enabled: true                            # false -> revert to LLM-only
```

- [ ] **Step 5: Run tests**

Run: `source myenv/Scripts/activate && pytest tests/test_core/test_settings_laya.py -v`
Expected: PASS.

Run: `source myenv/Scripts/activate && pytest --no-cov -q`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add budget_parser/config/settings.py budget_parser/config/default_config.yaml tests/test_core/test_settings_laya.py
git commit -m "feat: add laya configuration settings

Add laya_model, laya_confidence_threshold, laya_enabled to Settings
with sensible defaults. laya_enabled=false reverts to LLM-only."
```

---

### Task 3: Merchant Extractor — Regex-based merchant name cleaning

**Files:**
- Create: `budget_parser/categorizer/merchant_extractor.py`
- Test: `tests/test_categorizer/test_merchant_extractor.py` (new)

**Interfaces:**
- Consumes: nothing (standalone utility)
- Produces: `MerchantExtractor.extract(description: str) -> str` — returns cleaned, title-cased merchant name

- [ ] **Step 1: Write failing tests**

Create `tests/test_categorizer/test_merchant_extractor.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source myenv/Scripts/activate && pytest tests/test_categorizer/test_merchant_extractor.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement MerchantExtractor**

Create `budget_parser/categorizer/merchant_extractor.py`:

```python
"""Regex-based merchant name extraction from transaction descriptions."""

import re


_PREFIX_PATTERNS = [
    re.compile(r"^TST\*\s*", re.IGNORECASE),
    re.compile(r"^SQ\s*\*\s*", re.IGNORECASE),
    re.compile(r"^PP\*\s*", re.IGNORECASE),
    re.compile(r"^PAYPAL\s*\*\s*", re.IGNORECASE),
    re.compile(r"^Ant\*", re.IGNORECASE),
]

_STORE_NUMBER = re.compile(r"\s*#\d+\b")
_PHONE_NUMBER = re.compile(r"\d{3}[-.]?\d{3,}[-.]?\d{0,4}\w{0,2}")
_ZIP_CODE = re.compile(r"\b\d{5}(-\d{4})?\s*$")

_STATE_ABBREV = re.compile(
    r"\b(AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|"
    r"MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|"
    r"VA|WA|WV|WI|WY)\s*$"
)

_TRAILING_DOTCOM = re.compile(r"\.COM\b", re.IGNORECASE)

_KNOWN_CITIES = re.compile(
    r"\b(SPRINGFIELD|GRAND RAPIDS|DETROIT|CHICAGO|NEW YORK|LOS ANGELES|"
    r"SAN FRANCISCO|HOUSTON|DALLAS|AUSTIN|SEATTLE|PORTLAND|DENVER|PHOENIX|"
    r"COLUMBUS|INDIANAPOLIS|MINNEAPOLIS|NASHVILLE|ORLANDO|TAMPA|ATLANTA|"
    r"CHARLOTTE|RALEIGH|PITTSBURGH|CLEVELAND|CINCINNATI|MILWAUKEE|KANSAS CITY|"
    r"ST LOUIS|SALT LAKE CITY|LAS VEGAS|SAN DIEGO|SAN JOSE|SACRAMENTO|"
    r"JACKSONVILLE|MEMPHIS|LOUISVILLE|RICHMOND|BUFFALO|ROCHESTER|BIRMINGHAM)\b",
    re.IGNORECASE,
)


class MerchantExtractor:
    """Extracts clean merchant names from raw transaction descriptions using regex."""

    def extract(self, description: str) -> str:
        """Clean a transaction description into a merchant name.

        Args:
            description: Raw transaction description from bank statement

        Returns:
            Cleaned, title-cased merchant name. Empty string if input is blank.
        """
        text = description.strip()
        if not text:
            return ""

        for pattern in _PREFIX_PATTERNS:
            text = pattern.sub("", text)

        text = _STORE_NUMBER.sub("", text)
        text = _PHONE_NUMBER.sub("", text)
        text = _TRAILING_DOTCOM.sub("", text)
        text = _KNOWN_CITIES.sub("", text)
        text = _ZIP_CODE.sub("", text)
        text = _STATE_ABBREV.sub("", text)

        text = re.sub(r"[*#]+", " ", text)
        text = re.sub(r"\s+", " ", text).strip()

        if not text:
            return ""

        return text.title()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source myenv/Scripts/activate && pytest tests/test_categorizer/test_merchant_extractor.py -v`
Expected: All 12 tests PASS.

Iterate on regex patterns if any tests fail — the patterns above cover the documented examples but may need tuning for edge cases.

- [ ] **Step 5: Run full test suite**

Run: `source myenv/Scripts/activate && pytest --no-cov -q`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add budget_parser/categorizer/merchant_extractor.py tests/test_categorizer/test_merchant_extractor.py
git commit -m "feat: add regex-based merchant name extractor

General-purpose cleaner that strips prefixes, store numbers, phone
numbers, locations, and transaction codes from descriptions. Returns
title-cased merchant names without any LLM dependency."
```

---

### Task 4: Laya Categorizer — Two-step classification engine

**Files:**
- Create: `budget_parser/categorizer/laya_categorizer.py`
- Test: `tests/test_categorizer/test_laya_categorizer.py` (new)

**Interfaces:**
- Consumes: `get_categories(db_path)` from db.py (returns list of dicts with `category`, `sub_category`, `description`)
- Produces: `LayaCategorizer.__init__(self, categories: List[Dict], model: str, confidence_threshold: float)` and `LayaCategorizer.categorize(self, transactions: List[Dict]) -> List[Dict]` — returns same list with `category`, `sub_category`, `confidence`, `categorized_by` populated for accepted results

- [ ] **Step 1: Write failing tests**

Create `tests/test_categorizer/test_laya_categorizer.py`:

```python
"""Tests for laya two-step categorizer with mocked laya calls."""

from unittest.mock import patch, MagicMock
import pytest

from budget_parser.categorizer.laya_categorizer import LayaCategorizer


@pytest.fixture
def categories():
    return [
        {"category": "Grocery", "sub_category": "Grocery", "description": "grocery stores, supermarkets"},
        {"category": "Grocery", "sub_category": "Indian", "description": "Indian grocery stores"},
        {"category": "Restaurants", "sub_category": "Family", "description": "family restaurants"},
        {"category": "Restaurants", "sub_category": "Office", "description": "work lunches"},
        {"category": "Car", "sub_category": "Gas", "description": "gas stations, fuel"},
    ]


def _mock_predict(responses):
    """Create a mock router whose predict() returns responses in order."""
    mock_router = MagicMock()
    mock_router.predict = MagicMock(side_effect=responses)
    return mock_router


class TestLayaCategorizer:
    @patch("budget_parser.categorizer.laya_categorizer.Router")
    def test_high_confidence_categorization(self, mock_router_cls, categories):
        mock_router = MagicMock()
        mock_router.predict.side_effect = [
            # Step 1: category choice
            {"answers": {"category": {"choice": "Grocery", "confidence": 0.92, "distribution": {}}}},
            # Step 2: sub_category choice
            {"answers": {"sub_category": {"choice": "Grocery", "confidence": 0.88, "distribution": {}}}},
        ]
        mock_router_cls.return_value = mock_router

        cat = LayaCategorizer(categories, model="convaiinnovations/laya", confidence_threshold=0.6)
        transactions = [{"id": 1, "description": "KROGER #512 SPRINGFIELD IL", "category": ""}]
        result = cat.categorize(transactions)

        assert result[0]["category"] == "Grocery"
        assert result[0]["sub_category"] == "Grocery"
        assert result[0]["confidence"] == 0.88  # min(0.92, 0.88)
        assert result[0]["categorized_by"] == "laya"

    @patch("budget_parser.categorizer.laya_categorizer.Router")
    def test_low_confidence_skipped(self, mock_router_cls, categories):
        mock_router = MagicMock()
        mock_router.predict.side_effect = [
            {"answers": {"category": {"choice": "Car", "confidence": 0.45, "distribution": {}}}},
            {"answers": {"sub_category": {"choice": "Gas", "confidence": 0.90, "distribution": {}}}},
        ]
        mock_router_cls.return_value = mock_router

        cat = LayaCategorizer(categories, model="convaiinnovations/laya", confidence_threshold=0.6)
        transactions = [{"id": 1, "description": "AMBIGUOUS MERCHANT", "category": ""}]
        result = cat.categorize(transactions)

        assert result[0]["category"] == ""
        assert result[0].get("_laya_best_guess") == {
            "category": "Car", "sub_category": "Gas", "confidence": 0.45,
        }

    @patch("budget_parser.categorizer.laya_categorizer.Router")
    def test_skips_already_categorized(self, mock_router_cls, categories):
        mock_router = MagicMock()
        mock_router_cls.return_value = mock_router

        cat = LayaCategorizer(categories, model="convaiinnovations/laya", confidence_threshold=0.6)
        transactions = [{"id": 1, "description": "NETFLIX", "category": "Utilities"}]
        result = cat.categorize(transactions)

        assert result[0]["category"] == "Utilities"
        mock_router.predict.assert_not_called()

    @patch("budget_parser.categorizer.laya_categorizer.Router")
    def test_builds_category_criteria_from_descriptions(self, mock_router_cls, categories):
        mock_router = MagicMock()
        mock_router.predict.side_effect = [
            {"answers": {"category": {"choice": "Grocery", "confidence": 0.95, "distribution": {}}}},
            {"answers": {"sub_category": {"choice": "Indian", "confidence": 0.80, "distribution": {}}}},
        ]
        mock_router_cls.return_value = mock_router

        cat = LayaCategorizer(categories, model="convaiinnovations/laya", confidence_threshold=0.6)
        criteria = cat._category_criteria
        assert "Grocery" in criteria
        assert "Restaurants" in criteria
        assert "Car" in criteria

    @patch("budget_parser.categorizer.laya_categorizer.Router")
    def test_handles_laya_exception(self, mock_router_cls, categories):
        mock_router = MagicMock()
        mock_router.predict.side_effect = RuntimeError("model not loaded")
        mock_router_cls.return_value = mock_router

        cat = LayaCategorizer(categories, model="convaiinnovations/laya", confidence_threshold=0.6)
        transactions = [{"id": 1, "description": "KROGER", "category": ""}]
        result = cat.categorize(transactions)

        assert result[0]["category"] == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source myenv/Scripts/activate && pytest tests/test_categorizer/test_laya_categorizer.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement LayaCategorizer**

Create `budget_parser/categorizer/laya_categorizer.py`:

```python
"""Two-step laya-based transaction categorizer."""

from collections import defaultdict
from typing import Any, Dict, List

from laya import Router

from budget_parser.utils.logger import get_logger

logger = get_logger(__name__)


class LayaCategorizer:
    """Categorizes transactions using laya's choice primitive in two steps."""

    def __init__(
        self,
        categories: List[Dict[str, str]],
        model: str = "convaiinnovations/laya",
        confidence_threshold: float = 0.6,
    ):
        self._model = model
        self._threshold = confidence_threshold
        self._router = Router(preload=True)

        self._category_criteria, self._sub_criteria = self._build_criteria(categories)

    @staticmethod
    def _build_criteria(
        categories: List[Dict[str, str]],
    ) -> tuple:
        """Build laya criteria dicts from DB categories.

        Returns:
            (category_criteria, sub_criteria) where:
            - category_criteria: {"Grocery": "grocery stores, ...", ...}
            - sub_criteria: {"Grocery": {"Grocery": "general grocery", "Indian": "..."}, ...}
        """
        cat_descriptions: Dict[str, List[str]] = defaultdict(list)
        sub_criteria: Dict[str, Dict[str, str]] = defaultdict(dict)

        for row in categories:
            cat = row["category"]
            sub = row["sub_category"]
            desc = row.get("description", "").strip() or sub.lower()
            cat_descriptions[cat].append(desc)
            sub_criteria[cat][sub] = desc

        category_criteria = {
            cat: ", ".join(descs) for cat, descs in cat_descriptions.items()
        }
        return category_criteria, dict(sub_criteria)

    def _classify_one(self, description: str) -> Dict[str, Any]:
        """Run two-step classification on a single transaction description.

        Returns:
            {"category": str, "sub_category": str, "confidence": float}
            or {"category": "", "sub_category": "", "confidence": 0.0} on error.
        """
        empty = {"category": "", "sub_category": "", "confidence": 0.0}

        try:
            # Step 1: pick category
            step1 = self._router.predict(
                description,
                {
                    "category": {
                        "type": "choice",
                        "instructions": "What spending category does this transaction belong to?",
                        "criteria": self._category_criteria,
                    }
                },
            )
            cat_answer = step1["answers"]["category"]
            chosen_cat = cat_answer["choice"]
            cat_conf = cat_answer["confidence"]

            sub_options = self._sub_criteria.get(chosen_cat)
            if not sub_options:
                return empty

            # Step 2: pick sub_category
            step2 = self._router.predict(
                description,
                {
                    "sub_category": {
                        "type": "choice",
                        "instructions": f"What type of {chosen_cat.lower()} expense is this?",
                        "criteria": sub_options,
                    }
                },
            )
            sub_answer = step2["answers"]["sub_category"]
            chosen_sub = sub_answer["choice"]
            sub_conf = sub_answer["confidence"]

            return {
                "category": chosen_cat,
                "sub_category": chosen_sub,
                "confidence": min(cat_conf, sub_conf),
            }

        except Exception as e:
            logger.warning(f"Laya classification failed for '{description[:50]}': {e}")
            return empty

    def categorize(self, transactions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Categorize transactions using laya two-step classification.

        Skips already-categorized rows. For accepted results (confidence >= threshold),
        sets category, sub_category, confidence, and categorized_by. For low-confidence
        results, leaves category empty and stashes the best guess in _laya_best_guess.

        Args:
            transactions: List of transaction dicts with at least 'description'

        Returns:
            Same list with laya results applied where confident
        """
        results = [dict(tx) for tx in transactions]

        pending = [
            (i, tx)
            for i, tx in enumerate(results)
            if not tx.get("category", "").strip()
        ]

        if not pending:
            logger.info("Laya: all transactions already categorized.")
            return results

        logger.info(f"Laya: classifying {len(pending)} transaction(s)...")
        accepted = 0

        for i, tx in pending:
            classification = self._classify_one(tx["description"])
            conf = classification["confidence"]

            if conf >= self._threshold:
                results[i]["category"] = classification["category"]
                results[i]["sub_category"] = classification["sub_category"]
                results[i]["confidence"] = conf
                results[i]["categorized_by"] = "laya"
                accepted += 1
            elif classification["category"]:
                results[i]["_laya_best_guess"] = {
                    "category": classification["category"],
                    "sub_category": classification["sub_category"],
                    "confidence": conf,
                }

        logger.info(
            f"Laya: {accepted}/{len(pending)} accepted "
            f"(threshold={self._threshold}), "
            f"{len(pending) - accepted} routed to fallback"
        )
        return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source myenv/Scripts/activate && pytest tests/test_categorizer/test_laya_categorizer.py -v`
Expected: All 5 tests PASS.

- [ ] **Step 5: Run full test suite**

Run: `source myenv/Scripts/activate && pytest --no-cov -q`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add budget_parser/categorizer/laya_categorizer.py tests/test_categorizer/test_laya_categorizer.py
git commit -m "feat: add laya two-step transaction categorizer

Two-step classification: pick category (15 options), then
sub_category (2-6 options). Confidence = min of both steps.
Below threshold, stashes best guess for LLM fallback."
```

---

### Task 5: Wire up the four-tier categorization pipeline

**Files:**
- Modify: `budget_parser/cli/categorize.py`
- Test: `tests/test_cli/test_categorize_pipeline.py` (new)

**Interfaces:**
- Consumes: `LayaCategorizer.categorize()` from Task 4, `MerchantExtractor.extract()` from Task 3, `RegexCategorizer.categorize()` from existing code, `WebEnricher.enrich()` from existing code, `CategorizationAgent.categorize()` from existing code, `bulk_update_transaction_categories()` from Task 1, Settings fields from Task 2
- Produces: Updated `categorize_main(args)` with four-tier pipeline

- [ ] **Step 1: Write failing tests for the new pipeline**

Create `tests/test_cli/test_categorize_pipeline.py`:

```python
"""Tests for the four-tier categorization pipeline wiring."""

from unittest.mock import patch, MagicMock
import pytest

from budget_parser.database.db import (
    init_db, add_category, upsert_transactions, get_transactions,
)


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    add_category(path, "Grocery", "Grocery", "grocery stores")
    add_category(path, "Restaurants", "Family", "family restaurants")
    upsert_transactions(path, 2026, [
        {"date": "2026-01-15", "description": "KROGER #512 SPRINGFIELD IL", "amount": 55.00},
        {"date": "2026-01-16", "description": "AMBIGUOUS THING", "amount": 12.00},
    ])
    return path


class TestCategorizePipelineLaya:
    @patch("budget_parser.cli.categorize.CategorizationAgent")
    @patch("budget_parser.cli.categorize.WebEnricher")
    @patch("budget_parser.cli.categorize.LayaCategorizer")
    def test_laya_accepted_skips_llm(self, mock_laya_cls, mock_enricher_cls, mock_agent_cls, db_path):
        """When laya accepts all transactions, LLM should not be called."""
        mock_laya = MagicMock()
        mock_laya.categorize.return_value = [
            {
                "id": 1, "description": "KROGER #512", "category": "Grocery",
                "sub_category": "Grocery", "confidence": 0.9, "categorized_by": "laya",
                "amount": 55.00,
            },
            {
                "id": 2, "description": "AMBIGUOUS THING", "category": "Restaurants",
                "sub_category": "Family", "confidence": 0.85, "categorized_by": "laya",
                "amount": 12.00,
            },
        ]
        mock_laya_cls.return_value = mock_laya

        from budget_parser.cli.categorize import categorize_main
        from argparse import Namespace

        args = Namespace(
            config=None, db=db_path, log_level="WARNING", no_enrich=True,
            year=2026, test=False,
        )
        categorize_main(args)

        mock_agent_cls.return_value.categorize.assert_not_called()

    @patch("budget_parser.cli.categorize.CategorizationAgent")
    @patch("budget_parser.cli.categorize.WebEnricher")
    @patch("budget_parser.cli.categorize.LayaCategorizer")
    def test_low_confidence_falls_through_to_llm(self, mock_laya_cls, mock_enricher_cls, mock_agent_cls, db_path):
        """Low-confidence laya results should route to LLM fallback."""
        mock_laya = MagicMock()
        mock_laya.categorize.return_value = [
            {
                "id": 1, "description": "KROGER #512", "category": "Grocery",
                "sub_category": "Grocery", "confidence": 0.9, "categorized_by": "laya",
                "amount": 55.00,
            },
            {
                "id": 2, "description": "AMBIGUOUS THING", "category": "",
                "amount": 12.00,
                "_laya_best_guess": {"category": "Restaurants", "sub_category": "Family", "confidence": 0.4},
            },
        ]
        mock_laya_cls.return_value = mock_laya

        mock_agent = MagicMock()
        mock_agent.categorize.return_value = [
            {
                "id": 2, "description": "AMBIGUOUS THING", "category": "Restaurants",
                "sub_category": "Family", "merchant": "Ambiguous",
                "amount": 12.00,
            },
        ]
        mock_agent_cls.return_value = mock_agent

        from budget_parser.cli.categorize import categorize_main
        from argparse import Namespace

        args = Namespace(
            config=None, db=db_path, log_level="WARNING", no_enrich=True,
            year=2026, test=False,
        )
        categorize_main(args)

        mock_agent.categorize.assert_called_once()
        call_txs = mock_agent.categorize.call_args[0][0]
        assert len(call_txs) == 1
        assert call_txs[0]["id"] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source myenv/Scripts/activate && pytest tests/test_cli/test_categorize_pipeline.py -v`
Expected: FAIL — `LayaCategorizer` not imported in categorize.py.

- [ ] **Step 3: Rewrite categorize_main with the four-tier pipeline**

Replace the contents of `budget_parser/cli/categorize.py` with:

```python
"""Categorize subcommand — four-tier categorization pipeline."""

import sys
from datetime import datetime
from pathlib import Path

from budget_parser.categorizer.agent import CategorizationAgent
from budget_parser.categorizer.laya_categorizer import LayaCategorizer
from budget_parser.categorizer.merchant_extractor import MerchantExtractor
from budget_parser.categorizer.regex_categorizer import RegexCategorizer
from budget_parser.categorizer.web_enricher import WebEnricher
from budget_parser.config.settings import get_settings, reset_settings
from budget_parser.database.db import (
    bulk_update_transaction_categories,
    get_categories,
    get_regex_rules,
    get_transactions,
    get_uncategorized_transactions,
    init_db,
)
from budget_parser.utils.logger import get_logger, setup_logger


def add_parser(subparsers):
    p = subparsers.add_parser(
        "categorize",
        help="Categorize transactions using laya + LLM fallback",
        description="Categorize bank transactions. Reads uncategorized rows from DB and writes categories back.",
    )
    p.add_argument("--year", type=int, help="Statement year (default: current year)")
    p.add_argument("--config", type=str, help="Path to config.yaml")
    p.add_argument("--db", type=str, default="budget.db", help="SQLite DB path (default: budget.db)")
    p.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level",
    )
    p.add_argument(
        "--no-enrich",
        action="store_true",
        default=False,
        help="Skip web enrichment (for fast/offline runs)",
    )
    p.add_argument("--test", action="store_true", default=False, help="Use test.db and DEBUG logging")
    p.set_defaults(func=categorize_main)
    return p


def categorize_main(args) -> int:
    reset_settings()
    config_path = Path(args.config) if args.config else None
    settings = get_settings(config_path)

    if args.test:
        if args.db == "budget.db":
            args.db = "test.db"
        if args.log_level == "INFO":
            args.log_level = "DEBUG"

    if not args.test and args.db == "budget.db" and (Path.cwd() / "test.db").exists():
        print(
            "⚠ test.db exists — did you mean to use --test? Running against budget.db.",
            file=sys.stderr,
        )

    setup_logger(
        name="budget_parser",
        log_level=args.log_level,
        log_file=settings.log_file,
        max_bytes=settings.log_max_bytes,
        backup_count=settings.log_backup_count,
        console_output=True,
    )
    logger = get_logger("categorize")

    if args.year:
        year = args.year
    else:
        year = datetime.now().year
        logger.warning(
            f"--year not specified; defaulting to {year}. "
            "Pass --year explicitly to avoid ambiguity."
        )
    logger.info(f"Statement year: {year}")

    init_db(args.db)
    logger.info(f"Database: {args.db}")

    categories = get_categories(args.db)
    regex_rules = get_regex_rules(args.db, enabled_only=True)

    if not categories:
        logger.error("No categories in DB. Add category/sub-category pairs in the dashboard (Categories tab) and rerun.")
        return 1

    pending = get_uncategorized_transactions(args.db, year)
    if not pending:
        logger.info("Nothing to categorize — all transactions already have a category.")
        return 0

    logger.info(f"Found {len(pending)} uncategorized transaction(s).")

    # ---- Tier 1: Regex pre-pass ----
    if regex_rules:
        regex_cat = RegexCategorizer(regex_rules)
        pending = regex_cat.categorize(pending)
        regex_done = [tx for tx in pending if tx.get("category", "").strip()]
        if regex_done:
            for tx in regex_done:
                tx["confidence"] = 1.0
                tx["categorized_by"] = "regex"
            logger.info(f"Regex pre-pass categorized {len(regex_done)} transaction(s)")

    # Save regex results immediately
    regex_results = [tx for tx in pending if tx.get("categorized_by") == "regex"]
    if regex_results:
        bulk_update_transaction_categories(args.db, regex_results)

    # ---- Tier 2: Laya classification ----
    still_pending = [tx for tx in pending if not tx.get("category", "").strip()]

    if still_pending and settings.laya_enabled:
        laya_cat = LayaCategorizer(
            categories,
            model=settings.laya_model,
            confidence_threshold=settings.laya_confidence_threshold,
        )
        still_pending = laya_cat.categorize(still_pending)

        laya_done = [tx for tx in still_pending if tx.get("categorized_by") == "laya"]
        if laya_done:
            bulk_update_transaction_categories(args.db, laya_done)
            logger.info(f"Laya categorized {len(laya_done)} transaction(s)")

    # ---- Tier 3: Web enrichment + LLM fallback ----
    llm_pending = [tx for tx in still_pending if not tx.get("category", "").strip()]

    if llm_pending:
        if settings.web_enrichment_enabled and not args.no_enrich:
            enricher = WebEnricher(
                db_path=args.db,
                delay=settings.web_enrichment_delay,
                max_snippets=settings.web_enrichment_max_snippets,
                model=settings.web_enrichment_model,
            )
            llm_pending = enricher.enrich(llm_pending)
            enriched_count = sum(1 for tx in llm_pending if tx.get("context"))
            if enriched_count:
                logger.info(f"Web enrichment: added context for {enriched_count} transaction(s)")
        elif args.no_enrich:
            logger.info("Web enrichment skipped (--no-enrich flag)")

        agent = CategorizationAgent(
            model=settings.llm_model,
            categories=categories,
            temperature=settings.llm_temperature,
            top_p=settings.llm_top_p,
            num_predict=settings.llm_num_predict,
            batch_size=settings.categorize_batch_size,
        )
        llm_results = agent.categorize(llm_pending)

        llm_done = [tx for tx in llm_results if tx.get("category", "").strip() and tx.get("id")]
        for tx in llm_done:
            tx["categorized_by"] = "llm"
        if llm_done:
            bulk_update_transaction_categories(args.db, llm_done)
            logger.info(f"LLM fallback categorized {len(llm_done)} transaction(s)")

    # ---- Tier 4: Store laya best guesses for remaining uncategorized ----
    final_pending = [
        tx for tx in (llm_pending if llm_pending else still_pending)
        if not tx.get("category", "").strip() and tx.get("_laya_best_guess")
    ]
    if final_pending:
        for tx in final_pending:
            guess = tx["_laya_best_guess"]
            tx["category"] = guess["category"]
            tx["sub_category"] = guess["sub_category"]
            tx["confidence"] = guess["confidence"]
            tx["categorized_by"] = "laya"
        bulk_update_transaction_categories(args.db, final_pending)
        logger.info(f"Stored {len(final_pending)} low-confidence best guess(es) for review")

    # ---- Merchant extraction pass ----
    all_txs = get_transactions(args.db, year)
    merchant_extractor = MerchantExtractor()
    needs_merchant = [tx for tx in all_txs if not tx.get("merchant", "").strip()]
    if needs_merchant:
        merchant_updates = []
        for tx in needs_merchant:
            merchant = merchant_extractor.extract(tx["description"])
            if merchant:
                merchant_updates.append({
                    "id": tx["id"],
                    "category": tx.get("category", ""),
                    "sub_category": tx.get("sub_category", ""),
                    "merchant": merchant,
                    "confidence": tx.get("confidence"),
                    "categorized_by": tx.get("categorized_by"),
                })
        if merchant_updates:
            bulk_update_transaction_categories(args.db, merchant_updates)
            logger.info(f"Merchant extraction: filled {len(merchant_updates)} merchant name(s)")

    # ---- Summary ----
    all_txs = get_transactions(args.db, year)
    categorized_total = sum(1 for tx in all_txs if tx.get("category", "").strip())
    uncategorized_total = len(all_txs) - categorized_total
    logger.info(
        f"Summary: {categorized_total} categorized, {uncategorized_total} uncategorized"
        f" (total: {len(all_txs)})"
    )

    if uncategorized_total:
        logger.info(
            f"Tip: Add new category/sub-category pairs in the dashboard (Categories tab) "
            f"then rerun 'budget categorize --year {year}' to classify remaining transactions."
        )

    return 0
```

- [ ] **Step 4: Run tests**

Run: `source myenv/Scripts/activate && pytest tests/test_cli/test_categorize_pipeline.py -v`
Expected: Both tests PASS.

Run: `source myenv/Scripts/activate && pytest --no-cov -q`
Expected: All tests pass (existing categorize tests still work).

- [ ] **Step 5: Commit**

```bash
git add budget_parser/cli/categorize.py tests/test_cli/test_categorize_pipeline.py
git commit -m "feat: wire up four-tier categorization pipeline

Pipeline: regex -> laya -> web enrich+LLM -> flagged for review.
Laya rejects route to existing LLM fallback. Low-confidence best
guesses are stored for dashboard review. Merchant names are
extracted via regex as a final pass."
```

---

### Task 6: Add laya dependency to pyproject.toml

**Files:**
- Modify: `pyproject.toml:28-40`

**Interfaces:**
- Produces: `laya>=0.3.3` available for import

- [ ] **Step 1: Add laya to dependencies**

In `pyproject.toml`, add `"laya>=0.3.3",` to the `dependencies` list after the `duckduckgo-search` line:

```toml
dependencies = [
    "pdfplumber>=0.11.0",
    "ollama>=0.1.0",
    "pandas>=2.0.0",
    "pydantic>=2.5.0",
    "pydantic-settings>=2.0.0",
    "pyyaml>=6.0.0",
    "python-dotenv>=1.0.0",
    "streamlit>=1.35.0",
    "plotly>=5.18.0",
    "httpx>=0.27.0",
    "duckduckgo-search>=7.0.0",
    "laya>=0.3.3",
]
```

- [ ] **Step 2: Install the new dependency**

Run: `source myenv/Scripts/activate && pip install -e ".[dev]"`
Expected: laya installs successfully.

- [ ] **Step 3: Verify import works**

Run: `source myenv/Scripts/activate && python -c "import laya; print(laya.__version__)"`
Expected: Prints version number without error.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add laya dependency to pyproject.toml"
```

---

### Task 7: Dashboard — Surface confidence and categorized_by

**Files:**
- Modify: `budget_parser/dashboard/app.py`

**Interfaces:**
- Consumes: `get_transactions(db_path, year)` now returns `confidence` and `categorized_by` fields (from Task 1)

This task modifies the existing Streamlit dashboard. The file is 821 lines — changes are targeted to the Transactions tab and Overview tab.

- [ ] **Step 1: Add confidence and categorized_by columns to the Transactions tab**

In `budget_parser/dashboard/app.py`, find where the transactions DataFrame is displayed in the Transactions tab. Add the two new columns to the display, with color-coding for confidence:

The transactions DataFrame construction should include `confidence` and `categorized_by` from the DB rows. Add a helper function near the top of the file:

```python
def _confidence_color(val):
    """Color-code confidence values for the dataframe."""
    if val is None:
        return "color: gray"
    if val >= 0.8:
        return "color: green"
    if val >= 0.6:
        return "color: orange"
    return "color: red"
```

Where the transactions dataframe is built, ensure `confidence` and `categorized_by` are included as columns. Apply the style to the confidence column when displaying.

- [ ] **Step 2: Add categorized_by filter to the Transactions tab sidebar**

Add a multiselect filter in the sidebar for categorized_by values:

```python
available_methods = sorted(
    {tx.get("categorized_by") or "unknown" for tx in transactions}
)
selected_methods = st.sidebar.multiselect(
    "Categorized by", available_methods, default=available_methods
)
```

Filter the displayed transactions by the selected methods.

- [ ] **Step 3: Add laya stats card to the Overview tab**

In the Overview tab, add a summary showing the count by categorization method and average laya confidence:

```python
st.subheader("Categorization Methods")
method_counts = {}
laya_confidences = []
for tx in all_transactions:
    method = tx.get("categorized_by") or "unknown"
    method_counts[method] = method_counts.get(method, 0) + 1
    if method == "laya" and tx.get("confidence") is not None:
        laya_confidences.append(tx["confidence"])

cols = st.columns(len(method_counts))
for col, (method, count) in zip(cols, sorted(method_counts.items())):
    col.metric(method.title(), count)

if laya_confidences:
    avg_conf = sum(laya_confidences) / len(laya_confidences)
    st.metric("Avg Laya Confidence", f"{avg_conf:.1%}")
```

- [ ] **Step 4: Test the dashboard manually**

Run: `source myenv/Scripts/activate && python -m budget_parser serve`

Verify in the browser:
- Transactions tab shows confidence and categorized_by columns
- Confidence values are color-coded (green/yellow/red/gray)
- The sidebar filter for categorized_by works
- Overview tab shows the categorization methods breakdown

- [ ] **Step 5: Run full test suite**

Run: `source myenv/Scripts/activate && pytest --no-cov -q`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add budget_parser/dashboard/app.py
git commit -m "feat: surface confidence and categorized_by in dashboard

Add confidence column (color-coded) and categorized_by badge to
Transactions tab. Add method filter to sidebar. Add categorization
methods summary card to Overview tab."
```

---

### Task 8: Update config.yaml and LEARNINGS.md

**Files:**
- Modify: `config.yaml`
- Modify: `LEARNINGS.md`

- [ ] **Step 1: Add laya settings to the user's config.yaml**

Append to `config.yaml`:

```yaml

# Laya classification settings
laya_model: "convaiinnovations/laya"
laya_confidence_threshold: 0.6
laya_enabled: true
```

- [ ] **Step 2: Update LEARNINGS.md**

Add a session log entry and update the Architecture Summary to describe the new four-tier pipeline. Update the Key Files table to include `laya_categorizer.py` and `merchant_extractor.py`. Update the Design Decisions section to explain the laya choice.

- [ ] **Step 3: Run full test suite one final time**

Run: `source myenv/Scripts/activate && pytest --no-cov -q`
Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add config.yaml LEARNINGS.md
git commit -m "docs: update config and LEARNINGS for laya categorization"
```
