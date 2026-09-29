# Categorization Accuracy Improvements — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve categorization accuracy by rewriting category descriptions for laya and adding location-based vacation detection.

**Architecture:** Two independent changes: (1) a new `LocationCategorizer` class inserted as Tier 1.5 in the pipeline, and (2) a one-time DB migration that replaces auto-generated category descriptions with specific, disambiguating text.

**Tech Stack:** Python 3.9+, SQLite, Pydantic settings, pytest

## Global Constraints

- All tests must pass after each task (`pytest --no-cov -q`)
- Virtual environment: `source myenv/Scripts/activate` before every command
- Laya is stubbed in tests via `sys.modules.setdefault("laya", MagicMock())` in `tests/conftest.py`
- Use `categorized_by = "location"` (not "vacation" or "geo") for location-detected transactions
- Confidence for location matches = `0.9`
- Home state default = `"MI"`
- Online exclusion patterns: `.COM`, `WWW.`, `/BILL`, `ONLINE` (case-insensitive)
- State extraction regex must handle: trailing state (`CITY UT`), glued state (`KENTWOODMI`), state before dollar (`KENTWOODMI $86.86`), and state before negative dollar (`BENTONVILLEAR - $38.13`)
- Description migration must NOT overwrite descriptions that don't match the auto-generated pattern

---

### Task 1: Add `home_state` setting

**Files:**
- Modify: `budget_parser/config/settings.py:90-99`
- Modify: `budget_parser/config/default_config.yaml:59-62`
- Test: `tests/test_core/test_settings_laya.py`

**Interfaces:**
- Produces: `settings.home_state` → `str`, default `"MI"`

- [ ] **Step 1: Write failing test**

Add to `tests/test_core/test_settings_laya.py`:

```python
def test_home_state_default(tmp_path):
    """home_state defaults to MI."""
    config = tmp_path / "config.yaml"
    config.write_text("llm_model: llama3\n")
    reset_settings()
    s = get_settings(config)
    assert s.home_state == "MI"


def test_home_state_override(tmp_path):
    """home_state can be overridden in config."""
    config = tmp_path / "config.yaml"
    config.write_text("home_state: OH\n")
    reset_settings()
    s = get_settings(config)
    assert s.home_state == "OH"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_core/test_settings_laya.py -v --no-cov`
Expected: FAIL — `home_state` not a field on `Settings`

- [ ] **Step 3: Add `home_state` field to Settings**

In `budget_parser/config/settings.py`, after the `laya_enabled` field (line ~99), add:

```python
    # Location categorizer settings
    home_state: str = Field(
        default="MI", description="Two-letter home state/province code for vacation detection"
    )
```

- [ ] **Step 4: Add to default config**

In `budget_parser/config/default_config.yaml`, after the laya section, add:

```yaml
# Location-based vacation detection
home_state: "MI"                              # Transactions outside this state -> Vacation
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_core/test_settings_laya.py -v --no-cov`
Expected: PASS

- [ ] **Step 6: Run full suite**

Run: `pytest --no-cov -q`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add budget_parser/config/settings.py budget_parser/config/default_config.yaml tests/test_core/test_settings_laya.py
git commit -m "feat: add home_state setting for vacation detection"
```

---

### Task 2: Create `LocationCategorizer`

**Files:**
- Create: `budget_parser/categorizer/location_categorizer.py`
- Create: `tests/test_categorizer/test_location_categorizer.py`

**Interfaces:**
- Consumes: `home_state: str` from settings
- Produces: `LocationCategorizer.categorize(transactions: List[Dict]) -> List[Dict]` — same interface as `RegexCategorizer.categorize`. Modifies transactions in-place: sets `category="Vacation"`, `sub_category=""`, `confidence=0.9`, `categorized_by="location"` for non-home-state matches. Skips already-categorized rows and online-pattern matches.

- [ ] **Step 1: Write failing tests**

Create `tests/test_categorizer/test_location_categorizer.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_categorizer/test_location_categorizer.py -v --no-cov`
Expected: FAIL — module not found

- [ ] **Step 3: Implement LocationCategorizer**

Create `budget_parser/categorizer/location_categorizer.py`:

```python
"""Location-based vacation categorizer."""

import re
from typing import Any, Dict, List, Optional

from budget_parser.utils.logger import get_logger

logger = get_logger(__name__)

US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC",
}

CA_PROVINCES = {
    "AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE",
    "QC", "SK", "YT",
}

ALL_CODES = US_STATES | CA_PROVINCES

_ONLINE_RE = re.compile(r"\.COM|WWW\.|/BILL|ONLINE", re.IGNORECASE)

_STATE_RE = re.compile(
    r"([A-Z]{2})"
    r"(?:\s*-?\s*\$[\d.,]+)?"
    r"\s*$"
)


class LocationCategorizer:
    """Categorize out-of-state transactions as Vacation."""

    def __init__(self, home_state: str):
        self._home_state = home_state.upper().strip()

    def _extract_state(self, description: str) -> Optional[str]:
        """Extract the state/province code from a transaction description.

        Returns the two-letter code if found and valid, else None.
        """
        m = _STATE_RE.search(description.strip())
        if m:
            code = m.group(1)
            if code in ALL_CODES:
                return code
        return None

    def categorize(self, transactions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Tag out-of-state transactions as Vacation.

        Skips already-categorized rows, online transactions, and
        home-state matches. Does nothing if home_state is empty.
        """
        if not self._home_state:
            return transactions

        results = [dict(tx) for tx in transactions]
        tagged = 0

        for tx in results:
            if tx.get("category", "").strip():
                continue

            desc = tx.get("description", "")

            if _ONLINE_RE.search(desc):
                continue

            state = self._extract_state(desc)
            if state and state != self._home_state:
                tx["category"] = "Vacation"
                tx["sub_category"] = ""
                tx["confidence"] = 0.9
                tx["categorized_by"] = "location"
                tagged += 1

        if tagged:
            logger.info(f"Location categorizer: tagged {tagged} out-of-state transaction(s) as Vacation")

        return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_categorizer/test_location_categorizer.py -v --no-cov`
Expected: All PASS

- [ ] **Step 5: Run full suite**

Run: `pytest --no-cov -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add budget_parser/categorizer/location_categorizer.py tests/test_categorizer/test_location_categorizer.py
git commit -m "feat: add LocationCategorizer for out-of-state vacation detection"
```

---

### Task 3: Wire location categorizer into pipeline + migrate descriptions

**Files:**
- Modify: `budget_parser/cli/categorize.py:1-10,111-128`
- Modify: `budget_parser/database/db.py:197-215`
- Modify: `tests/test_cli/test_categorize_pipeline.py`
- Modify: `tests/test_core/test_db_schema.py`

**Interfaces:**
- Consumes: `LocationCategorizer` from Task 2, `settings.home_state` from Task 1
- Consumes: `bulk_update_transaction_categories` from `db.py`
- Produces: Tier 1.5 in the pipeline (after regex save, before laya)
- Produces: `migrate_category_descriptions(db_path)` function in `db.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_cli/test_categorize_pipeline.py`:

```python
@patch("budget_parser.cli.categorize.auto_populate_category_descriptions")
@patch("budget_parser.cli.categorize.get_transactions")
@patch("budget_parser.cli.categorize.bulk_update_transaction_categories")
@patch("budget_parser.cli.categorize.get_uncategorized_transactions")
@patch("budget_parser.cli.categorize.get_regex_rules", return_value=[])
@patch("budget_parser.cli.categorize.get_categories", return_value=[
    {"category": "Restaurants", "sub_category": "Family", "description": "family dining"},
])
@patch("budget_parser.cli.categorize.init_db")
def test_location_categorizer_tags_vacation(
    mock_init, mock_cats, mock_rules, mock_uncat,
    mock_bulk, mock_txs, mock_auto, tmp_path
):
    """Out-of-state transaction is tagged as Vacation before laya."""
    mock_uncat.return_value = [
        {"id": 1, "description": "SHAKE SHACK LAS LAS VEGAS NV", "category": ""},
    ]
    mock_txs.return_value = []

    args = argparse.Namespace(
        year=2026, config=None, db=str(tmp_path / "test.db"),
        log_level="WARNING", no_enrich=True, test=False,
    )
    categorize_main(args)

    bulk_calls = mock_bulk.call_args_list
    location_call = bulk_calls[0]
    saved = location_call[0][1]
    assert any(tx["categorized_by"] == "location" and tx["category"] == "Vacation" for tx in saved)
```

Add to `tests/test_core/test_db_schema.py`:

```python
def test_migrate_descriptions_updates_auto_generated(tmp_path):
    """migrate_category_descriptions replaces auto-generated descriptions."""
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    add_category(db_path, "Car", "Gas", "gas (car)")
    add_category(db_path, "Utilities", "Gas", "gas (utilities)")

    from budget_parser.database.db import migrate_category_descriptions
    count = migrate_category_descriptions(db_path)

    cats = get_categories(db_path)
    car_gas = next(c for c in cats if c["category"] == "Car" and c["sub_category"] == "Gas")
    util_gas = next(c for c in cats if c["category"] == "Utilities" and c["sub_category"] == "Gas")
    assert "gas station" in car_gas["description"].lower()
    assert "utility" in util_gas["description"].lower()
    assert count >= 2


def test_migrate_descriptions_preserves_custom(tmp_path):
    """migrate_category_descriptions does not overwrite custom descriptions."""
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    add_category(db_path, "Car", "Gas", "my custom description for gas")

    from budget_parser.database.db import migrate_category_descriptions
    migrate_category_descriptions(db_path)

    cats = get_categories(db_path)
    car_gas = next(c for c in cats if c["category"] == "Car" and c["sub_category"] == "Gas")
    assert car_gas["description"] == "my custom description for gas"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cli/test_categorize_pipeline.py::test_location_categorizer_tags_vacation tests/test_core/test_db_schema.py::test_migrate_descriptions_updates_auto_generated tests/test_core/test_db_schema.py::test_migrate_descriptions_preserves_custom -v --no-cov`
Expected: FAIL

- [ ] **Step 3: Add `migrate_category_descriptions` to `db.py`**

Add after `auto_populate_category_descriptions` in `budget_parser/database/db.py`:

```python
# Map of (category, sub_category) -> improved description
_IMPROVED_DESCRIPTIONS = {
    ("Car", "Gas"): "gas stations, fuel, Shell, BP, Speedway, Meijer gas",
    ("Car", "Insurance"): "auto insurance, car insurance premium, Progressive, Geico",
    ("Car", "Service"): "auto repair, oil change, tire, mechanic, dealership service, car wash",
    ("Car", "Taxi"): "taxi, cab fare, airport shuttle",
    ("Entertainment", "Events"): "concerts, shows, theme parks, sporting events, tickets, museum",
    ("Entertainment", "Movies"): "movie theater, cinema, AMC, Regal, Celebration Cinema",
    ("Entertainment", "Streaming"): "movie rentals, pay-per-view, Fandango, Vudu",
    ("Grocery", "Grocery"): "grocery stores, supermarkets, Meijer, Kroger, Aldi, food shopping",
    ("Grocery", "Indian"): "Indian grocery, Indian market, Spice of India, specialty spices",
    ("Grooming", "Clothes"): "clothing stores, apparel, shoes, fashion retail",
    ("Grooming", "Haircut"): "haircut, salon, barber, Great Clips, hair styling",
    ("Grooming", "Makeup"): "cosmetics, beauty products, skincare, Sephora, Ulta",
    ("Hobby", "Books"): "books, bookstore, Kindle, audiobooks, reading apps",
    ("Hobby", "Learning"): "online courses, education, training, Claude, ChatGPT, AI tools",
    ("Hobby", "Pickleball"): "pickleball courts, paddles, pickleball equipment",
    ("Hobby", "YMCA"): "YMCA membership, gym fees, fitness center",
    ("House", "Aquarium"): "aquarium supplies, fish, pet store aquarium",
    ("House", "Association Fee"): "HOA fee, homeowner association dues, community fee",
    ("House", "Insurance"): "homeowner insurance, home insurance, dwelling policy",
    ("House", "Mortgage"): "mortgage payment, home loan, escrow",
    ("House", "Ring"): "Ring doorbell, home security subscription",
    ("India", "Parents"): "wire transfer to India, remittance, family support",
    ("Kids Activity", "Ice Skating"): "ice skating rink, skating lessons, Patterson Ice",
    ("Kids Activity", "Music"): "music lessons, piano, instrument classes, music school",
    ("Kids Activity", "Swimming"): "swim lessons, pool membership, swimming class",
    ("Kids Activity", "Toys"): "toy stores, games, LEGO, children's toys",
    ("Kids Activity", "YMCA"): "kids YMCA programs, youth activities, day camp",
    ("Medical", "Dentist"): "dentist, dental, orthodontist, teeth cleaning, eye doctor, optometrist",
    ("Misc", "Gifts"): "gifts, presents, jewelry, department store, Kate Spade, Coach, Perfumania",
    ("Misc", "Photo"): "photography, photo prints, Shutterfly, portrait studio",
    ("Online Shopping", "Amazon"): "Amazon, Amazon Marketplace, Amzn, Prime purchases",
    ("Restaurants", "Bubble"): "bubble tea, boba, smoothie, juice bar, Surf City Squeeze",
    ("Restaurants", "Family"): "family dining, sit-down restaurants, casual dining, takeout, fast food",
    ("Restaurants", "Office"): "work lunch, office meal, business dining",
    ("Tax", "Income"): "income tax, tax payment, IRS, state tax",
    ("Utilities", "Cloud Storage"): "iCloud, Google One, cloud storage subscription, Apple storage",
    ("Utilities", "Electricity"): "electric bill, power company, DTE Energy, Consumers Energy",
    ("Utilities", "Gas"): "natural gas utility bill, gas utility, heating",
    ("Utilities", "Internet"): "internet service, ISP, Comcast, Xfinity, broadband",
    ("Utilities", "Phone"): "cell phone bill, mobile plan, T-Mobile, Verizon, AT&T",
    ("Utilities", "Streaming"): "Netflix, Hulu, Disney+, YouTube TV, Paramount+, HBO, streaming subscription",
    ("Vacation", "Bahamas"): "Bahamas cruise, Royal Caribbean, Caribbean vacation",
    ("Vacation", "Detroit"): "Detroit area trip, Sterling Heights, Canton, Troy",
    ("Vacation", "Minnesota"): "Minnesota trip, Mall of America, Bloomington MN",
    ("Vacation", "Ohio"): "Ohio trip, Hocking Hills, Logan OH",
    ("Vacation", "Orlando"): "Orlando trip, Universal Studios, Florida vacation",
    ("Vacation", "Toronto"): "Toronto trip, Ontario Canada, Niagara",
    ("Vacation", "Utah"): "Utah trip, Bryce Canyon, Zion, Cedar City, Las Vegas",
}


def migrate_category_descriptions(db_path: str) -> int:
    """Replace auto-generated category descriptions with improved ones.

    Only updates rows whose current description matches the auto-generated
    pattern (``sub (cat)`` or ``sub``) or is empty. Custom descriptions are
    preserved. Returns the number of rows updated.
    """
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT id, category, sub_category, description FROM categories"
        ).fetchall()
        count = 0
        for row in rows:
            key = (row["category"], row["sub_category"])
            improved = _IMPROVED_DESCRIPTIONS.get(key)
            if not improved:
                continue

            current = row["description"].strip()
            sub_lower = row["sub_category"].lower()
            auto_pattern = f"{sub_lower} ({row['category'].lower()})"

            if current == "" or current == sub_lower or current == auto_pattern:
                conn.execute(
                    "UPDATE categories SET description = ? WHERE id = ?",
                    (improved, row["id"]),
                )
                count += 1

        conn.commit()
        return count
    finally:
        conn.close()
```

- [ ] **Step 4: Call `migrate_category_descriptions` from `init_db`**

In `budget_parser/database/db.py`, at the end of `init_db` (after the `_migrate_add_column` calls, before `finally`), add:

```python
        migrate_category_descriptions(db_path)
```

Wait — `init_db` takes `db_path` as a string but `migrate_category_descriptions` also takes `db_path`. This is fine since `migrate_category_descriptions` opens its own connection.

Actually, `init_db` should call it outside the `try/finally` block since `migrate_category_descriptions` manages its own connection. Add the call right after `conn.close()` in the `finally`, as a new line after the `init_db` function's existing body. Alternatively, call it at the end of `init_db` before `finally:`. Since `_migrate_add_column` already committed, it's safe:

After line `_migrate_add_column(conn, "categories", "description", "TEXT NOT NULL DEFAULT ''")` and before `finally:`, add:

```python
        conn.close()
        migrate_category_descriptions(db_path)
        return
```

Then in the `finally:` block, guard the close:

Actually, simpler: just call `migrate_category_descriptions(db_path)` after the existing `finally: conn.close()` block — as a top-level call at the end of `init_db`. The function opens and closes its own connection.

```python
def init_db(db_path: str) -> None:
    # ... existing code ...
    conn = get_connection(db_path)
    try:
        # ... existing schema + migrations ...
    finally:
        conn.close()

    migrate_category_descriptions(db_path)
```

- [ ] **Step 5: Simplify `auto_populate_category_descriptions`**

In `budget_parser/database/db.py`, update `auto_populate_category_descriptions`. Change the description generation from `"{sub} ({cat})"` to just the sub_category name as-is. Replace:

```python
            desc = row["sub_category"].lower()
            if row["category"].lower() != row["sub_category"].lower():
                desc = f"{row['sub_category'].lower()} ({row['category'].lower()})"
```

With:

```python
            desc = row["sub_category"]
```

This means new categories added via the dashboard get a plain sub_category name as their initial description, which the user can then edit to be more specific. The old pattern (`"gas (car)"`) was actively harmful to laya.

- [ ] **Step 6: Wire `LocationCategorizer` into `categorize.py`**

In `budget_parser/cli/categorize.py`:

Add import at top:
```python
from budget_parser.categorizer.location_categorizer import LocationCategorizer
```

After the regex results save block (after `bulk_update_transaction_categories(args.db, regex_results)`), before `# ---- Tier 2: Laya classification ----`, insert:

```python
    # ---- Tier 1.5: Location-based vacation detection ----
    still_pending = [tx for tx in pending if not tx.get("category", "").strip()]

    if still_pending and settings.home_state:
        location_cat = LocationCategorizer(settings.home_state)
        still_pending = location_cat.categorize(still_pending)

        location_done = [tx for tx in still_pending if tx.get("categorized_by") == "location"]
        if location_done:
            bulk_update_transaction_categories(args.db, location_done)
            logger.info(f"Location categorizer: {len(location_done)} out-of-state transaction(s) -> Vacation")
```

Then update the existing Tier 2 block: the `still_pending` variable is already computed above, so remove the duplicate line:
```python
    # ---- Tier 2: Laya classification ----
    still_pending = [tx for tx in pending if not tx.get("category", "").strip()]  # DELETE THIS LINE
```

The `still_pending` from Tier 1.5 already filters out categorized rows. But the laya block needs to re-filter since location_cat.categorize returns all rows (including tagged ones):

```python
    # ---- Tier 2: Laya classification ----
    still_pending = [tx for tx in still_pending if not tx.get("category", "").strip()]
```

This is the same pattern — just sourcing from `still_pending` instead of `pending`.

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/test_cli/test_categorize_pipeline.py tests/test_core/test_db_schema.py -v --no-cov`
Expected: All PASS

- [ ] **Step 8: Run full suite**

Run: `pytest --no-cov -q`
Expected: All pass

- [ ] **Step 9: Commit**

```bash
git add budget_parser/cli/categorize.py budget_parser/database/db.py tests/test_cli/test_categorize_pipeline.py tests/test_core/test_db_schema.py
git commit -m "feat: wire location categorizer + migrate category descriptions"
```

---

### Task 4: Update README, LEARNINGS, and dashboard pipeline text

**Files:**
- Modify: `README.md`
- Modify: `LEARNINGS.md`

**Interfaces:**
- Consumes: completed Tasks 1-3

- [ ] **Step 1: Update README**

In the **Stage 2 — Categorize** section, update the pipeline diagram to show Tier 1.5:

```
Tier 1: RegexCategorizer     fast pre-pass using regex rules from budget.db
  |                           confidence = 1.0, categorized_by = "regex"
  v
Tier 1.5: LocationCategorizer out-of-state transactions -> Vacation
  |                           confidence = 0.9, categorized_by = "location"
  v
Tier 2: LayaCategorizer       two-step laya classification (category -> sub_category)
```

In the **Configuration** table, add:

| `home_state` | `MI` | Two-letter state code; transactions outside this state are tagged as Vacation |

In the **Troubleshooting** table, add:

| Online orders tagged as Vacation | Add a regex rule for that merchant in the dashboard (regex runs before location detection) |

In the **Features** section, add or update the vacation detection bullet.

- [ ] **Step 2: Update LEARNINGS.md**

Add `location_categorizer.py` to Key Files table. Update the pipeline description. Add session log entry.

- [ ] **Step 3: Commit**

```bash
git add README.md LEARNINGS.md
git commit -m "docs: update README and LEARNINGS for location categorizer + improved descriptions"
```
