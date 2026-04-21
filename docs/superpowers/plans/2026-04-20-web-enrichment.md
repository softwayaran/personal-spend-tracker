# Web-Enriched Categorization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a DuckDuckGo-based web enrichment stage that provides business context to the LLM before transaction categorization, with persistent caching in SQLite.

**Architecture:** New `WebEnricher` class sits between regex pre-pass and LLM categorization. It normalizes descriptions, checks a `merchant_cache` DB table, searches DuckDuckGo for cache misses, summarizes results via local LLM, caches them, and appends context to transaction descriptions. The `CategorizationAgent` prompt format changes minimally to include the appended context.

**Tech Stack:** Python 3.9+, httpx (HTTP client), BeautifulSoup4 (HTML parsing), Ollama (summarization), SQLite (caching)

---

## File Structure

| File | Responsibility |
|------|----------------|
| `budget_parser/categorizer/web_enricher.py` (create) | WebEnricher class: normalization, cache lookup, search, summarization, context attachment |
| `budget_parser/categorizer/description_normalizer.py` (create) | Pure functions for cleaning transaction descriptions into search queries/cache keys |
| `budget_parser/database/db.py` (modify) | Add `merchant_cache` table to `init_db`, add cache CRUD functions |
| `budget_parser/config/settings.py` (modify) | Add web enrichment settings fields |
| `budget_parser/categorizer/agent.py` (modify) | Update `_build_prompt` to include context field |
| `budget_parser/cli/categorize.py` (modify) | Wire in WebEnricher, add `--no-enrich` flag |
| `pyproject.toml` (modify) | Add httpx, beautifulsoup4 dependencies |
| `tests/test_categorizer/test_description_normalizer.py` (create) | Tests for normalization logic |
| `tests/test_categorizer/test_web_enricher.py` (create) | Tests for enricher with mocked HTTP/LLM |
| `tests/test_categorizer/__init__.py` (create) | Package init |

---

### Task 1: Add Dependencies

**Files:**
- Modify: `pyproject.toml:28-38`

- [ ] **Step 1: Add httpx and beautifulsoup4 to dependencies**

In `pyproject.toml`, add to the `dependencies` list:

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
    "beautifulsoup4>=4.12.0",
]
```

- [ ] **Step 2: Install updated dependencies**

Run: `source myenv/Scripts/activate && pip install -e .`
Expected: Installs httpx and beautifulsoup4 successfully.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "feat: add httpx and beautifulsoup4 for web enrichment"
```

---

### Task 2: Description Normalizer

**Files:**
- Create: `budget_parser/categorizer/description_normalizer.py`
- Create: `tests/test_categorizer/__init__.py`
- Create: `tests/test_categorizer/test_description_normalizer.py`

- [ ] **Step 1: Write failing tests for normalization**

Create `tests/test_categorizer/__init__.py` (empty file).

Create `tests/test_categorizer/test_description_normalizer.py`:

```python
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
    assert normalize_description("Ant*MoboreaderHongKongChinaHK") == "Moboreader"


def test_already_clean_description():
    assert normalize_description("NETFLIX") == "NETFLIX"


def test_removes_transaction_id_patterns():
    assert normalize_description("Netflix.com408-5403700CA") == "Netflix.com"


def test_empty_string():
    assert normalize_description("") == ""


def test_whitespace_collapsing():
    assert normalize_description("  SOME   MERCHANT   ") == "SOME MERCHANT"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source myenv/Scripts/activate && pytest tests/test_categorizer/test_description_normalizer.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the normalizer**

Create `budget_parser/categorizer/description_normalizer.py`:

```python
"""Pure functions for cleaning transaction descriptions into search queries and cache keys."""

import re


_PREFIX_PATTERNS = [
    re.compile(r"^TST\*\s*", re.IGNORECASE),
    re.compile(r"^SQ\s*\*\s*", re.IGNORECASE),
    re.compile(r"^PP\*\s*", re.IGNORECASE),
    re.compile(r"^Ant\*", re.IGNORECASE),
]

_TRAILING_CODE_PATTERN = re.compile(r"[*]\w{5,}$")

_PHONE_OR_ID_PATTERN = re.compile(r"\d{3}[-.]?\d{3,}[-.]?\d{0,4}\w{0,2}$")

_STORE_NUMBER_PATTERN = re.compile(r"#\d+", re.IGNORECASE)

_STATE_ZIP_PATTERN = re.compile(
    r"\b[A-Z]{2}\s*\d{5}(-\d{4})?\s*$"
)

_TRAILING_STATE_PATTERN = re.compile(
    r"\b(AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY)\s*$"
)

_TRAILING_COUNTRY_CODE = re.compile(
    r"\b(US|CA|UK|GB|AU|HK|CN|IN|JP|DE|FR|IT|ES|NL|BR|MX)\s*$", re.IGNORECASE
)

_COUNTRY_CITY_SUFFIX = re.compile(
    r"(Hong\s*Kong|China|United\s*States|Canada|Australia)\w*\s*$", re.IGNORECASE
)


def normalize_description(description: str) -> str:
    """Normalize a transaction description into a clean search query / cache key.

    Strips merchant prefixes, trailing transaction codes, store numbers,
    state abbreviations, zip codes, and country codes.
    """
    text = description.strip()
    if not text:
        return ""

    for pattern in _PREFIX_PATTERNS:
        text = pattern.sub("", text)

    text = _PHONE_OR_ID_PATTERN.sub("", text)
    text = _TRAILING_CODE_PATTERN.sub("", text)
    text = _STORE_NUMBER_PATTERN.sub("", text)
    text = _STATE_ZIP_PATTERN.sub("", text)
    text = _TRAILING_STATE_PATTERN.sub("", text)
    text = _TRAILING_COUNTRY_CODE.sub("", text)
    text = _COUNTRY_CITY_SUFFIX.sub("", text)

    text = re.sub(r"\s+", " ", text).strip()

    return text
```

- [ ] **Step 4: Run tests and iterate until passing**

Run: `source myenv/Scripts/activate && pytest tests/test_categorizer/test_description_normalizer.py -v`
Expected: All tests pass. Some regex patterns may need tuning — iterate until all assertions hold.

- [ ] **Step 5: Commit**

```bash
git add budget_parser/categorizer/description_normalizer.py tests/test_categorizer/
git commit -m "feat: add description normalizer for web enrichment cache keys"
```

---

### Task 3: Database — merchant_cache Table

**Files:**
- Modify: `budget_parser/database/db.py:27-66` (init_db function)
- Modify: `budget_parser/database/db.py` (add new functions at end)

- [ ] **Step 1: Write failing tests for cache CRUD**

Create `tests/test_categorizer/test_merchant_cache_db.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source myenv/Scripts/activate && pytest tests/test_categorizer/test_merchant_cache_db.py -v`
Expected: FAIL with `ImportError` (functions don't exist yet)

- [ ] **Step 3: Add merchant_cache table to init_db**

In `budget_parser/database/db.py`, add to the `init_db` function's `executescript` call, after the `idx_transactions_year` index:

```python
            CREATE TABLE IF NOT EXISTS merchant_cache (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                description_pattern TEXT NOT NULL UNIQUE,
                merchant_name       TEXT NOT NULL DEFAULT '',
                business_type       TEXT NOT NULL DEFAULT '',
                created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
```

- [ ] **Step 4: Add cache CRUD functions**

Append to `budget_parser/database/db.py`:

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `source myenv/Scripts/activate && pytest tests/test_categorizer/test_merchant_cache_db.py -v`
Expected: All 4 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add budget_parser/database/db.py tests/test_categorizer/test_merchant_cache_db.py
git commit -m "feat: add merchant_cache table and CRUD for web enrichment"
```

---

### Task 4: Settings — Web Enrichment Config

**Files:**
- Modify: `budget_parser/config/settings.py:76` (after categorize_batch_size)

- [ ] **Step 1: Add web enrichment settings to Settings class**

Add these fields to the `Settings` class in `budget_parser/config/settings.py`, after `categorize_batch_size`:

```python
    # Web enrichment settings
    web_enrichment_enabled: bool = Field(default=True, description="Enable web search enrichment")
    web_enrichment_delay: float = Field(
        default=1.5, ge=0.0, description="Seconds between DuckDuckGo requests"
    )
    web_enrichment_max_snippets: int = Field(
        default=3, gt=0, description="Number of search results to grab"
    )
    web_enrichment_model: str = Field(
        default="llama3", description="Ollama model for summarizing search results"
    )
```

- [ ] **Step 2: Verify settings load correctly**

Run: `source myenv/Scripts/activate && python -c "from budget_parser.config.settings import Settings; s = Settings(); print(s.web_enrichment_enabled, s.web_enrichment_delay)"`
Expected: `True 1.5`

- [ ] **Step 3: Commit**

```bash
git add budget_parser/config/settings.py
git commit -m "feat: add web enrichment settings (enabled, delay, max_snippets, model)"
```

---

### Task 5: WebEnricher Class

**Files:**
- Create: `budget_parser/categorizer/web_enricher.py`
- Create: `tests/test_categorizer/test_web_enricher.py`

- [ ] **Step 1: Write failing tests for WebEnricher**

Create `tests/test_categorizer/test_web_enricher.py`:

```python
"""Tests for WebEnricher with mocked HTTP and LLM calls."""

import os
import tempfile
from unittest.mock import patch, MagicMock

import pytest

from budget_parser.categorizer.web_enricher import WebEnricher
from budget_parser.database.db import init_db, get_merchant_cache


@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    yield path
    os.unlink(path)


@pytest.fixture
def enricher(db_path):
    return WebEnricher(db_path=db_path, delay=0.0, max_snippets=2, model="llama3")


def _mock_search_response(snippet_text: str) -> MagicMock:
    """Create a mock httpx response with DuckDuckGo-like HTML."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = f'<div class="result__snippet">{snippet_text}</div>'
    return mock_resp


class TestWebEnricher:
    @patch("budget_parser.categorizer.web_enricher.httpx.get")
    @patch("budget_parser.categorizer.web_enricher.ollama.chat")
    def test_enriches_uncategorized_transaction(self, mock_ollama, mock_httpx, enricher):
        mock_httpx.return_value = _mock_search_response(
            "Thai Fusion is a Thai restaurant in Grand Rapids"
        )
        mock_ollama.return_value = {
            "message": {"content": "Thai restaurant"}
        }

        transactions = [
            {"id": 1, "description": "TST* THAI FUSION GRAND RAPIDS MI", "category": ""}
        ]
        result = enricher.enrich(transactions)

        assert result[0]["context"] == "Thai restaurant"

    @patch("budget_parser.categorizer.web_enricher.httpx.get")
    @patch("budget_parser.categorizer.web_enricher.ollama.chat")
    def test_uses_cache_on_second_call(self, mock_ollama, mock_httpx, enricher):
        mock_httpx.return_value = _mock_search_response("Amazon online store")
        mock_ollama.return_value = {"message": {"content": "online retail store"}}

        transactions = [{"id": 1, "description": "AMZN MKTP US*ABC123", "category": ""}]
        enricher.enrich(transactions)

        mock_httpx.reset_mock()
        mock_ollama.reset_mock()

        result = enricher.enrich(transactions)
        assert result[0]["context"] == "online retail store"
        mock_httpx.assert_not_called()
        mock_ollama.assert_not_called()

    def test_skips_already_categorized(self, enricher):
        transactions = [
            {"id": 1, "description": "NETFLIX", "category": "Utilities"}
        ]
        result = enricher.enrich(transactions)
        assert "context" not in result[0]

    @patch("budget_parser.categorizer.web_enricher.httpx.get")
    def test_handles_search_failure_gracefully(self, mock_httpx, enricher):
        mock_httpx.side_effect = Exception("Network error")

        transactions = [{"id": 1, "description": "UNKNOWN MERCHANT", "category": ""}]
        result = enricher.enrich(transactions)

        assert result[0].get("context", "") == ""

    @patch("budget_parser.categorizer.web_enricher.httpx.get")
    def test_caches_no_result(self, mock_httpx, enricher, db_path):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body>No results</body></html>"
        mock_httpx.return_value = mock_resp

        transactions = [{"id": 1, "description": "XYZZY GIBBERISH", "category": ""}]
        enricher.enrich(transactions)

        cached = get_merchant_cache(db_path, "XYZZY GIBBERISH")
        assert cached is not None
        assert cached["business_type"] == "no_result"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source myenv/Scripts/activate && pytest tests/test_categorizer/test_web_enricher.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement WebEnricher**

Create `budget_parser/categorizer/web_enricher.py`:

```python
"""Web-based transaction description enrichment using DuckDuckGo search."""

import time
from typing import Dict, List, Optional

import httpx
import ollama
from bs4 import BeautifulSoup

from budget_parser.categorizer.description_normalizer import normalize_description
from budget_parser.database.db import get_merchant_cache, upsert_merchant_cache
from budget_parser.utils.logger import get_logger

logger = get_logger(__name__)

_SEARCH_URL = "https://html.duckduckgo.com/html/"
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


class WebEnricher:
    """Enriches transaction descriptions with business context from web search."""

    def __init__(
        self,
        db_path: str,
        delay: float = 1.5,
        max_snippets: int = 3,
        model: str = "llama3",
    ):
        self.db_path = db_path
        self.delay = delay
        self.max_snippets = max_snippets
        self.model = model

    def enrich(self, transactions: List[Dict]) -> List[Dict]:
        """Enrich uncategorized transactions with web-searched business context.

        Adds a 'context' field to each transaction that was enriched.
        Already-categorized transactions are skipped.
        """
        results = [dict(tx) for tx in transactions]

        for tx in results:
            if tx.get("category", "").strip():
                continue

            description = tx.get("description", "")
            normalized = normalize_description(description)
            if not normalized:
                continue

            context = self._get_context(normalized)
            if context and context != "no_result":
                tx["context"] = context

        return results

    def _get_context(self, normalized_description: str) -> Optional[str]:
        """Get business context: from cache or via web search + LLM summary."""
        cached = get_merchant_cache(self.db_path, normalized_description)
        if cached:
            return cached["business_type"]

        snippets = self._search(normalized_description)
        if not snippets:
            upsert_merchant_cache(self.db_path, normalized_description, "", "no_result")
            return "no_result"

        summary = self._summarize(normalized_description, snippets)
        merchant_name = normalized_description.split()[0] if normalized_description else ""
        upsert_merchant_cache(self.db_path, normalized_description, merchant_name, summary)

        if self.delay > 0:
            time.sleep(self.delay)

        return summary

    def _search(self, query: str) -> List[str]:
        """Search DuckDuckGo and return snippet texts."""
        try:
            response = httpx.get(
                _SEARCH_URL,
                params={"q": f"{query} merchant"},
                headers={"User-Agent": _USER_AGENT},
                timeout=10.0,
            )
            if response.status_code != 200:
                logger.warning(f"Search returned status {response.status_code} for '{query}'")
                return []

            soup = BeautifulSoup(response.text, "html.parser")
            snippet_elements = soup.select(".result__snippet")
            snippets = [el.get_text(strip=True) for el in snippet_elements[: self.max_snippets]]

            if not snippets:
                logger.debug(f"No search snippets found for '{query}'")

            return snippets

        except Exception as e:
            logger.warning(f"Search failed for '{query}': {e}")
            return []

    def _summarize(self, description: str, snippets: List[str]) -> str:
        """Use local LLM to summarize search snippets into a business type."""
        snippets_text = "\n".join(f"- {s}" for s in snippets)
        prompt = (
            f"Based on these search results about '{description}', "
            f"what type of business or service is this? Reply in 5 words or fewer.\n\n"
            f"Search results:\n{snippets_text}"
        )

        try:
            response = ollama.chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                options={"temperature": 0.1, "num_predict": 20},
            )
            return response["message"]["content"].strip()
        except Exception as e:
            logger.warning(f"Summarization failed for '{description}': {e}")
            return snippets[0][:50] if snippets else ""
```

- [ ] **Step 4: Run tests and iterate**

Run: `source myenv/Scripts/activate && pytest tests/test_categorizer/test_web_enricher.py -v`
Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add budget_parser/categorizer/web_enricher.py tests/test_categorizer/test_web_enricher.py
git commit -m "feat: implement WebEnricher with DuckDuckGo search and LLM summarization"
```

---

### Task 6: Update CategorizationAgent Prompt

**Files:**
- Modify: `budget_parser/categorizer/agent.py:52-57`

- [ ] **Step 1: Write a test for context-aware prompt building**

Add to `tests/test_categorizer/test_web_enricher.py` (or create a new file `tests/test_categorizer/test_agent_prompt.py`):

```python
"""Tests for CategorizationAgent prompt with context."""

from budget_parser.categorizer.agent import CategorizationAgent


def test_prompt_includes_context_when_present():
    agent = CategorizationAgent(
        model="llama3",
        categories=[{"category": "Restaurants", "sub_category": "Family"}],
    )
    transactions = [
        {"index": 0, "description": "TST* THAI FUSION", "context": "Thai restaurant"},
        {"index": 1, "description": "NETFLIX", },
    ]
    prompt = agent._build_prompt(transactions)
    assert "(Context: Thai restaurant)" in prompt
    assert "NETFLIX" in prompt
    assert "(Context:" not in prompt.split("NETFLIX")[1].split("\n")[0]


def test_prompt_works_without_context():
    agent = CategorizationAgent(
        model="llama3",
        categories=[{"category": "Utilities", "sub_category": "Streaming"}],
    )
    transactions = [
        {"index": 0, "description": "NETFLIX"},
    ]
    prompt = agent._build_prompt(transactions)
    assert "0: NETFLIX" in prompt
    assert "Context" not in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source myenv/Scripts/activate && pytest tests/test_categorizer/test_agent_prompt.py -v`
Expected: `test_prompt_includes_context_when_present` FAILS (context not appended yet)

- [ ] **Step 3: Update _build_prompt to include context**

In `budget_parser/categorizer/agent.py`, replace the `_build_prompt` method's transaction line building (lines 54-57):

```python
    def _build_prompt(self, transactions: List[Dict[str, Any]]) -> str:
        """Build the categorization prompt for a batch of transactions."""
        tx_lines = []
        for item in transactions:
            line = f'{item["index"]}: {item["description"]}'
            if item.get("context"):
                line += f' (Context: {item["context"]})'
            tx_lines.append(line)
        tx_text = "\n".join(tx_lines)
```

Then replace `{tx_lines}` in the f-string with `{tx_text}`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `source myenv/Scripts/activate && pytest tests/test_categorizer/test_agent_prompt.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add budget_parser/categorizer/agent.py tests/test_categorizer/test_agent_prompt.py
git commit -m "feat: include web enrichment context in categorization prompt"
```

---

### Task 7: Wire Into CLI

**Files:**
- Modify: `budget_parser/cli/categorize.py`

- [ ] **Step 1: Add --no-enrich flag to argument parser**

In `budget_parser/cli/categorize.py`, in the `add_parser` function, add after the `--log-level` argument:

```python
    p.add_argument(
        "--no-enrich",
        action="store_true",
        default=False,
        help="Skip web enrichment (for fast/offline runs)",
    )
```

- [ ] **Step 2: Import WebEnricher and wire into categorize_main**

Add import at top of file:

```python
from budget_parser.categorizer.web_enricher import WebEnricher
```

In `categorize_main`, after the regex pre-pass block (after line 88) and before `agent = CategorizationAgent(...)`, add:

```python
    # Web enrichment pass
    if settings.web_enrichment_enabled and not args.no_enrich:
        enricher = WebEnricher(
            db_path=args.db,
            delay=settings.web_enrichment_delay,
            max_snippets=settings.web_enrichment_max_snippets,
            model=settings.web_enrichment_model,
        )
        pending = enricher.enrich(pending)
        enriched_count = sum(1 for tx in pending if tx.get("context"))
        if enriched_count:
            logger.info(f"Web enrichment: added context for {enriched_count} transaction(s)")
    elif args.no_enrich:
        logger.info("Web enrichment skipped (--no-enrich flag)")
```

- [ ] **Step 3: Update CategorizationAgent call to pass context**

In the `categorize_main` function, the agent's `categorize` method already passes transactions through. The `_build_prompt` change from Task 6 will pick up the `context` field automatically. No additional change needed here — the `pending` list already carries the `context` field after enrichment.

However, we need to make sure the `indexed` list inside `CategorizationAgent.categorize` includes the context. Modify `budget_parser/categorizer/agent.py` in the `categorize` method (around line 168):

```python
            indexed = [
                {"index": j, "description": tx["description"], "context": tx.get("context", "")}
                for j, tx in enumerate(batch_txs)
            ]
```

- [ ] **Step 4: Test the full CLI flow manually**

Run: `source myenv/Scripts/activate && python -m budget_parser categorize --year 2025 --no-enrich`
Expected: Runs without errors, logs "Web enrichment skipped (--no-enrich flag)"

Run: `source myenv/Scripts/activate && python -m budget_parser categorize --year 2025`
Expected: Runs with web enrichment enabled (will attempt searches if uncategorized transactions exist)

- [ ] **Step 5: Run full test suite**

Run: `source myenv/Scripts/activate && pytest -v`
Expected: All tests pass (existing + new).

- [ ] **Step 6: Commit**

```bash
git add budget_parser/cli/categorize.py budget_parser/categorizer/agent.py
git commit -m "feat: wire web enrichment into categorize CLI with --no-enrich flag"
```

---

### Task 8: Integration Test

**Files:**
- Create: `tests/test_categorizer/test_enrichment_integration.py`

- [ ] **Step 1: Write an integration test covering the full enrichment flow**

Create `tests/test_categorizer/test_enrichment_integration.py`:

```python
"""Integration test for the full web enrichment → categorization flow."""

import os
import tempfile
from unittest.mock import patch, MagicMock

import pytest

from budget_parser.categorizer.web_enricher import WebEnricher
from budget_parser.categorizer.agent import CategorizationAgent
from budget_parser.database.db import init_db, get_merchant_cache


@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    yield path
    os.unlink(path)


@patch("budget_parser.categorizer.web_enricher.httpx.get")
@patch("budget_parser.categorizer.web_enricher.ollama.chat")
def test_enrichment_feeds_into_categorization_prompt(mock_ollama_enrich, mock_httpx, db_path):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = '<div class="result__snippet">Thai Fusion is a Thai restaurant</div>'
    mock_httpx.return_value = mock_resp
    mock_ollama_enrich.return_value = {"message": {"content": "Thai restaurant"}}

    enricher = WebEnricher(db_path=db_path, delay=0.0)
    transactions = [
        {"id": 1, "description": "TST* THAI FUSION GRAND RAPIDS MI", "category": ""},
    ]
    enriched = enricher.enrich(transactions)

    assert enriched[0]["context"] == "Thai restaurant"

    agent = CategorizationAgent(
        model="llama3",
        categories=[{"category": "Restaurants", "sub_category": "Family"}],
    )
    indexed = [{"index": 0, "description": enriched[0]["description"], "context": enriched[0].get("context", "")}]
    prompt = agent._build_prompt(indexed)

    assert "(Context: Thai restaurant)" in prompt
    assert "TST* THAI FUSION GRAND RAPIDS MI" in prompt


@patch("budget_parser.categorizer.web_enricher.httpx.get")
@patch("budget_parser.categorizer.web_enricher.ollama.chat")
def test_cached_result_skips_network(mock_ollama, mock_httpx, db_path):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = '<div class="result__snippet">Starbucks coffee chain</div>'
    mock_httpx.return_value = mock_resp
    mock_ollama.return_value = {"message": {"content": "Coffee chain"}}

    enricher = WebEnricher(db_path=db_path, delay=0.0)
    transactions = [{"id": 1, "description": "STARBUCKS #12345", "category": ""}]

    enricher.enrich(transactions)
    assert mock_httpx.call_count == 1

    mock_httpx.reset_mock()
    mock_ollama.reset_mock()

    result = enricher.enrich(transactions)
    assert result[0]["context"] == "Coffee chain"
    mock_httpx.assert_not_called()
```

- [ ] **Step 2: Run integration tests**

Run: `source myenv/Scripts/activate && pytest tests/test_categorizer/test_enrichment_integration.py -v`
Expected: All tests PASS.

- [ ] **Step 3: Run full test suite one final time**

Run: `source myenv/Scripts/activate && pytest -v`
Expected: All tests pass, no regressions.

- [ ] **Step 4: Commit**

```bash
git add tests/test_categorizer/test_enrichment_integration.py
git commit -m "test: add integration test for web enrichment pipeline"
```

---

## Summary

| Task | What it delivers |
|------|-----------------|
| 1 | Dependencies (httpx, beautifulsoup4) |
| 2 | Description normalizer (pure functions, tested) |
| 3 | `merchant_cache` DB table + CRUD |
| 4 | Settings fields for web enrichment config |
| 5 | `WebEnricher` class (search + summarize + cache) |
| 6 | Updated LLM prompt to include context |
| 7 | CLI wiring + `--no-enrich` flag |
| 8 | Integration test proving end-to-end flow |
