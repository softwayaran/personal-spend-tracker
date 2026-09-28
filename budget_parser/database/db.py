"""SQLite database layer for personal budget tool.

All SQLite interaction is here. Functions are flat (no classes) for simplicity.
``budget.db`` lives at the project root; ``year`` column scopes transactions.
Categories and regex rules are global (not per-year).
"""

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from budget_parser.utils.date_parser import normalize_statement_date


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------

def get_connection(db_path: str) -> sqlite3.Connection:
    """Open SQLite connection with WAL mode and Row factory. Caller must close."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


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

    migrate_category_descriptions(db_path)


def _migrate_add_column(conn: sqlite3.Connection, table: str, column: str, col_type: str) -> None:
    """Add a column if it doesn't exist. Silently ignores duplicates."""
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # column already exists


# ---------------------------------------------------------------------------
# Categories CRUD
# ---------------------------------------------------------------------------

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


def update_category(
    db_path: str, category_id: int, new_category: str, new_sub_category: str
) -> int:
    """Rename a category/sub_category pair and cascade-update all matching transactions.

    If the new name already exists as a separate row, the old row is deleted and
    transactions are merged into the existing entry (no duplicate categories).

    Returns the number of transactions updated.
    """
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT category, sub_category FROM categories WHERE id = ?", (category_id,)
        ).fetchone()
        if not row:
            return 0
        old_cat, old_sub = row["category"], row["sub_category"]

        if old_cat == new_category and old_sub == new_sub_category:
            return 0  # nothing changed

        # Check whether the target name already exists as a different row
        existing = conn.execute(
            "SELECT id FROM categories WHERE category = ? AND sub_category = ? AND id != ?",
            (new_category, new_sub_category, category_id),
        ).fetchone()

        if existing:
            # Merge: delete old row, transactions will point at existing entry
            conn.execute("DELETE FROM categories WHERE id = ?", (category_id,))
        else:
            conn.execute(
                "UPDATE categories SET category = ?, sub_category = ? WHERE id = ?",
                (new_category, new_sub_category, category_id),
            )

        # Cascade to transactions
        cursor = conn.execute(
            "UPDATE transactions SET category = ?, sub_category = ?"
            " WHERE category = ? AND sub_category = ?",
            (new_category, new_sub_category, old_cat, old_sub),
        )
        tx_count = cursor.rowcount
        conn.commit()
        return tx_count
    finally:
        conn.close()


def delete_category(db_path: str, category_id: int) -> None:
    """Delete a category by id. Does NOT cascade to transactions."""
    conn = get_connection(db_path)
    try:
        conn.execute("DELETE FROM categories WHERE id = ?", (category_id,))
        conn.commit()
    finally:
        conn.close()


def update_category_description(db_path: str, category_id: int, description: str) -> None:
    """Update the laya criteria description for a category."""
    conn = get_connection(db_path)
    try:
        conn.execute(
            "UPDATE categories SET description = ? WHERE id = ?",
            (description, category_id),
        )
        conn.commit()
    finally:
        conn.close()


def auto_populate_category_descriptions(db_path: str) -> int:
    """Fill empty category descriptions with a default derived from the name.

    Returns the number of rows updated.
    """
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT id, category, sub_category FROM categories WHERE description = ''"
        ).fetchall()
        count = 0
        for row in rows:
            desc = row["sub_category"]
            conn.execute(
                "UPDATE categories SET description = ? WHERE id = ?",
                (desc, row["id"]),
            )
            count += 1
        if count:
            conn.commit()
        return count
    finally:
        conn.close()


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

            if current == "" or current == sub_lower or current == row["sub_category"] or current == auto_pattern:
                conn.execute(
                    "UPDATE categories SET description = ? WHERE id = ?",
                    (improved, row["id"]),
                )
                count += 1

        if count:
            conn.commit()
        return count
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Regex Rules CRUD
# ---------------------------------------------------------------------------

def get_regex_rules(db_path: str, enabled_only: bool = False) -> List[Dict]:
    """Return regex rules ordered by priority, id."""
    conn = get_connection(db_path)
    try:
        q = "SELECT id, priority, pattern, category, sub_category, merchant, enabled FROM regex_rules"
        if enabled_only:
            q += " WHERE enabled = 1"
        q += " ORDER BY priority, id"
        rows = conn.execute(q).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def add_regex_rule(
    db_path: str,
    pattern: str,
    category: str,
    sub_category: str,
    merchant: str,
    priority: int = 0,
    enabled: bool = True,
) -> int:
    """Insert a new regex rule. Returns the new row id."""
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            """INSERT INTO regex_rules
               (pattern, category, sub_category, merchant, priority, enabled)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (pattern, category, sub_category, merchant, priority, 1 if enabled else 0),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def update_regex_rule(
    db_path: str,
    rule_id: int,
    *,
    pattern: Optional[str] = None,
    category: Optional[str] = None,
    sub_category: Optional[str] = None,
    merchant: Optional[str] = None,
    priority: Optional[int] = None,
    enabled: Optional[bool] = None,
) -> None:
    """Update one or more fields on a regex rule."""
    updates: Dict[str, Any] = {}
    if pattern is not None:
        updates["pattern"] = pattern
    if category is not None:
        updates["category"] = category
    if sub_category is not None:
        updates["sub_category"] = sub_category
    if merchant is not None:
        updates["merchant"] = merchant
    if priority is not None:
        updates["priority"] = priority
    if enabled is not None:
        updates["enabled"] = 1 if enabled else 0
    if not updates:
        return

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [rule_id]

    conn = get_connection(db_path)
    try:
        conn.execute(f"UPDATE regex_rules SET {set_clause} WHERE id = ?", values)
        conn.commit()
    finally:
        conn.close()


def delete_regex_rule(db_path: str, rule_id: int) -> None:
    """Delete a regex rule by id."""
    conn = get_connection(db_path)
    try:
        conn.execute("DELETE FROM regex_rules WHERE id = ?", (rule_id,))
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------

def _normalize_date(date_str: str, year: int) -> str:
    """Convert MM/DD to YYYY-MM-DD if needed. YYYY-MM-DD passes through unchanged."""
    if len(date_str) == 10 and date_str[4] == "-":
        return date_str  # already YYYY-MM-DD

    normalized = normalize_statement_date(date_str)
    if not normalized:
        raise ValueError(f"Unsupported date format: {date_str}")

    parts = normalized.split("/")
    month = int(parts[0])
    day = int(parts[1])
    return f"{year:04d}-{month:02d}-{day:02d}"


def upsert_transactions(
    db_path: str, year: int, transactions: List[Dict]
) -> Dict[str, int]:
    """Insert transactions into DB, skipping duplicates.

    Returns {'inserted': N, 'skipped': N}.
    """
    conn = get_connection(db_path)
    inserted = skipped = 0
    try:
        for tx in transactions:
            date = _normalize_date(tx["date"], year)
            amount_raw = tx["amount"]
            try:
                amount = float(amount_raw)
            except (ValueError, TypeError):
                amount = float(str(amount_raw).replace("$", "").replace(",", ""))

            cursor = conn.execute(
                """INSERT OR IGNORE INTO transactions
                   (year, date, description, amount, category, sub_category, merchant)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    year,
                    date,
                    tx["description"],
                    amount,
                    tx.get("category", ""),
                    tx.get("sub_category", ""),
                    tx.get("merchant", ""),
                ),
            )
            if cursor.rowcount > 0:
                inserted += 1
            else:
                skipped += 1
        conn.commit()
    finally:
        conn.close()
    return {"inserted": inserted, "skipped": skipped}


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


def bulk_update_transactions(db_path: str, updates: List[Dict]) -> int:
    """Update full transaction rows by id.

    Each dict must contain: id, year, date, description, amount.
    Category/sub_category/merchant default to empty string if missing.
    Returns count of rows updated.
    """
    params = []
    for tx in updates:
        tx_id = tx.get("id")
        if tx_id is None:
            continue

        date = str(tx.get("date", "")).strip()
        if not date:
            continue

        try:
            year = int(tx.get("year"))
        except (TypeError, ValueError):
            continue

        amount_raw = tx.get("amount")
        try:
            amount = float(amount_raw)
        except (ValueError, TypeError):
            amount = float(str(amount_raw).replace("$", "").replace(",", ""))

        params.append(
            (
                year,
                date,
                str(tx.get("description", "")).strip(),
                amount,
                str(tx.get("category", "")).strip(),
                str(tx.get("sub_category", "")).strip(),
                str(tx.get("merchant", "")).strip(),
                int(tx_id),
            )
        )

    if not params:
        return 0

    conn = get_connection(db_path)
    try:
        conn.executemany(
            """UPDATE transactions
               SET year = ?, date = ?, description = ?, amount = ?, category = ?, sub_category = ?, merchant = ?
               WHERE id = ?""",
            params,
        )
        conn.commit()
        return len(params)
    finally:
        conn.close()


def delete_transaction(db_path: str, tx_id: int) -> None:
    """Delete a single transaction by id."""
    conn = get_connection(db_path)
    try:
        conn.execute("DELETE FROM transactions WHERE id = ?", (tx_id,))
        conn.commit()
    finally:
        conn.close()


def get_available_years(db_path: str) -> List[int]:
    """Return distinct years with transactions, descending. Returns [] if DB missing."""
    if not Path(db_path).exists():
        return []
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT DISTINCT year FROM transactions ORDER BY year DESC"
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Merchant Cache
# ---------------------------------------------------------------------------

def get_merchant_cache(db_path: str, description_pattern: str) -> Optional[Dict]:
    """Look up cached merchant info by normalized description. Returns None on miss."""
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT merchant_name, business_type, created_at FROM merchant_cache WHERE description_pattern = ?",
            (description_pattern,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def upsert_merchant_cache(
    db_path: str, description_pattern: str, merchant_name: str, business_type: str
) -> None:
    """Insert or update a merchant cache entry."""
    conn = get_connection(db_path)
    try:
        conn.execute(
            """INSERT INTO merchant_cache (description_pattern, merchant_name, business_type)
               VALUES (?, ?, ?)
               ON CONFLICT(description_pattern)
               DO UPDATE SET merchant_name = excluded.merchant_name,
                            business_type = excluded.business_type,
                            created_at = CURRENT_TIMESTAMP""",
            (description_pattern, merchant_name, business_type),
        )
        conn.commit()
    finally:
        conn.close()

