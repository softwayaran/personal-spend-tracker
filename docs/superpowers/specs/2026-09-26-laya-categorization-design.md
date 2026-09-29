# Design Spec: Laya-Based Transaction Categorization

**Date:** 2026-09-26
**Status:** Draft
**Branch:** `feat/categorization-redesign`

## Problem

Transaction categorization currently relies entirely on Ollama LLM calls. This is slow
(seconds per batch), requires a running Ollama instance with a large model, and produces
unstructured JSON that needs parsing and validation. The LLM sometimes hallucinates categories
or returns malformed responses, requiring retry logic.

## Solution

Replace the LLM with [laya](https://laya.convaiinnovations.com/) as the primary categorization
engine. Laya is a non-autoregressive, bidirectional classifier (System 1 decision model) that
returns calibrated probabilities over structured schemas in ~33ms. It eliminates hallucination
risk since it can only select from predefined options, not generate text.

The LLM is kept as a fallback for low-confidence transactions, and web enrichment feeds into
that fallback path only.

## New Categorization Pipeline

Four-tier waterfall. Each tier only processes transactions left uncategorized by the previous one:

```
Uncategorized transactions (from DB)
        |
        v
   +--------------+
   | 1. Regex      |  Unchanged. First-match wins from DB rules.
   |    pre-pass   |  Sets confidence = 1.0, categorized_by = "regex".
   +------+-------+
          | still uncategorized
          v
   +--------------+
   | 2. Laya       |  NEW. Two-step choice (category -> sub_category).
   |    classify   |  Confidence >= 0.6 -> accept (categorized_by = "laya").
   |               |  Confidence < 0.6  -> skip, route to tier 3.
   +------+-------+
          | low-confidence only
          v
   +--------------+
   | 3. Web        |  Existing enricher + Ollama LLM.
   |    enrich +   |  Only runs on laya rejects.
   |    LLM        |  Sets categorized_by = "llm".
   +------+-------+
          | still uncategorized
          v
   +--------------+
   | 4. Flagged    |  Laya's best guess stored with its low confidence
   |    for review |  score. Visible in dashboard for manual review.
   +--------------+
```

### Tier behaviors

- **Regex matches**: confidence = 1.0, categorized_by = "regex".
- **Laya >= 0.6**: accepted directly, categorized_by = "laya".
- **Laya < 0.6**: routed to web enrichment + LLM fallback. If LLM produces a result,
  categorized_by = "llm", confidence = NULL (Ollama doesn't produce calibrated scores).
- **Nothing works**: laya's best guess is stored with its low confidence score so the user
  can review and correct in the dashboard.

## Laya Two-Step Classification

45 category/sub_category pairs across 15 top-level categories. Laya's accuracy degrades
above ~20 options, so classification uses two sequential `choice` calls:

### Step 1 — Pick the category (15 options)

```python
state = "KROGER #512 SPRINGFIELD IL"
questions = {
    "category": {
        "type": "choice",
        "instructions": "What spending category does this transaction belong to?",
        "criteria": {
            "Car": "gas, insurance, service, taxi, ride",
            "Grocery": "grocery stores, supermarkets, food shopping",
            # ... all 15 categories with short descriptions
        }
    }
}
result = router.predict(state, questions)
```

### Step 2 — Pick the sub_category (2-6 options)

```python
# category chosen = "Grocery"
questions = {
    "sub_category": {
        "type": "choice",
        "instructions": "What type of grocery purchase is this?",
        "criteria": {
            "Grocery": "general grocery stores, supermarkets",
            "Indian": "Indian grocery stores, specialty ingredients"
        }
    }
}
result = router.predict(state, questions)
```

### Confidence

Overall confidence = min(step 1 confidence, step 2 confidence). If either step falls
below 0.6, the transaction routes to the LLM fallback.

### Category criteria descriptions

Each category and sub_category needs a short text description for laya's `criteria` dict.
These are built from the category names (most are self-describing). Stored alongside
categories in the DB so they can be edited in the dashboard if needed.

## Merchant Name Extraction

A general-purpose regex cleaner replaces the LLM-based merchant extraction. Runs as a
final pass on any transaction with an empty `merchant` field (regex categorizer rules
already set merchants for their matches).

### Stripping rules (applied in order)

1. Common prefixes: `SQ *`, `TST*`, `PP*`, `PAYPAL *`
2. Phone numbers: `408-5403700`, `800-123-4567`
3. Store/branch numbers: `#512`, `#1234`, `Store 0042`
4. Transaction codes: trailing alphanumeric IDs, card suffixes
5. Trailing location info: city, state abbreviations, ZIP codes
6. Excessive whitespace and special characters

Result is title-cased.

### Examples

| Raw Description                    | Cleaned Merchant      |
|------------------------------------|-----------------------|
| `KROGER #512 SPRINGFIELD IL`       | `Kroger`              |
| `SQ *BLUE BOTTLE COFFEE`          | `Blue Bottle Coffee`  |
| `NETFLIX.COM408-5403700CA`         | `Netflix`             |
| `AMAZONMKTPL`                      | `Amazon Mktpl`        |
| `OLIVE GARDEN #1234 SPRINGFIELD`   | `Olive Garden`        |

### Implementation

New class `MerchantExtractor` in `budget_parser/categorizer/merchant_extractor.py`.
Chain of regex substitutions, then title-case. No DB rules, no LLM — pure pattern matching.

## Database Schema Changes

### `categories` table — new column

```sql
ALTER TABLE categories ADD COLUMN description TEXT NOT NULL DEFAULT '';
```

Short text description used as laya's `criteria` value for that category/sub_category.
Auto-populated from the category name on first run (e.g., "Car" -> "car expenses").
Editable in the dashboard's Categories tab. When empty, the category name is used as-is.

### `transactions` table — two new columns

```sql
ALTER TABLE transactions ADD COLUMN confidence REAL DEFAULT NULL;
ALTER TABLE transactions ADD COLUMN categorized_by TEXT DEFAULT NULL;
```

### `confidence` column

- `NULL` — legacy rows (pre-laya) or LLM-categorized (no calibrated score)
- `1.0` — regex categorizer match (deterministic)
- `0.0-1.0` — laya's calibrated probability (min of the two steps)

### `categorized_by` column

- `NULL` — legacy or uncategorized
- `"regex"` — regex pre-pass
- `"laya"` — laya classification
- `"llm"` — Ollama LLM fallback
- `"manual"` — user edited in dashboard

### Migration approach

`ALTER TABLE ... ADD COLUMN` in `init_db`, wrapped in try/except for the "duplicate column"
error. Upgrades existing `budget.db` files in place on first run. A proper migration system
is out of scope for this change.

## Dashboard Changes

Three additions to existing tabs (no new tabs):

### 1. Confidence column in Transactions tab

- Show confidence score (0.0-1.0) in the transactions data table
- Color-coded: green (>= 0.8), yellow (0.6-0.8), red (< 0.6), gray (NULL/legacy)
- Sortable for quick review of low-confidence transactions

### 2. "Categorized by" indicator

- Small badge/tag per transaction row: `regex`, `laya`, `llm`, or `manual`
- Filterable in the sidebar

### 3. Laya stats in Overview tab

- Summary card: transaction count by categorization method (regex / laya / llm / manual)
- Average confidence score for laya-categorized transactions

## Configuration

### New config.yaml settings

```yaml
# Laya classification settings
laya_model: "convaiinnovations/laya"
laya_confidence_threshold: 0.6
laya_enabled: true
```

### Settings class fields

- `laya_model: str = "convaiinnovations/laya"` — HuggingFace checkpoint
- `laya_confidence_threshold: float = 0.6` — below this, fall back to LLM
- `laya_enabled: bool = True` — set False to revert to pure-LLM behavior

### Escape hatch

`laya_enabled: false` skips laya entirely and routes all transactions to the existing
LLM pipeline. This ensures the old behavior is always recoverable without code changes.

## Dependencies

### New

- `laya>=0.3.3` in `pyproject.toml` (Apache 2.0, downloads ~808 MB model on first use)

### Unchanged

- Ollama remains required for: LLM fallback, web enrichment summarization, PDF extraction
- `--no-enrich` flag still works — skips web enrichment in the LLM fallback tier

## File Changes

### New files

| File                                          | Purpose                                                    |
|-----------------------------------------------|------------------------------------------------------------|
| `budget_parser/categorizer/laya_categorizer.py` | Two-step laya classification, model loading, confidence    |
| `budget_parser/categorizer/merchant_extractor.py` | General-purpose regex cleaner for merchant names          |
| `tests/test_categorizer/test_laya_categorizer.py` | Two-step classification, confidence thresholds, edge cases |
| `tests/test_categorizer/test_merchant_extractor.py` | Pattern stripping, title-casing, edge cases              |

### Modified files

| File                                    | Change                                                          |
|-----------------------------------------|-----------------------------------------------------------------|
| `budget_parser/cli/categorize.py`       | Wire up four-tier pipeline: regex -> laya -> enrich+LLM -> flag |
| `budget_parser/categorizer/agent.py`    | Receives smaller batch of laya rejects (no structural changes)  |
| `budget_parser/database/db.py`          | ALTER TABLE for new columns; update bulk_update to accept them  |
| `budget_parser/config/settings.py`      | Add laya_model, laya_confidence_threshold, laya_enabled fields  |
| `budget_parser/config/default_config.yaml` | Add laya settings with defaults                              |
| `budget_parser/dashboard/app.py`        | Confidence column, categorized-by badges, laya stats card       |
| `pyproject.toml`                        | Add laya>=0.3.3 dependency                                     |

### Unchanged

- `regex_categorizer.py` — stays as-is
- `web_enricher.py` — stays as-is, called on fewer transactions
- `pipeline.py` (extraction) — untouched
- All existing tests — should still pass
