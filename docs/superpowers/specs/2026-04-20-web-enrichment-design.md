# Web-Enriched Categorization

## Summary

Add a web enrichment stage to the categorization pipeline that searches DuckDuckGo for transaction descriptions the regex pre-pass didn't handle. Search results are summarized by the local LLM into a short business-type context string, cached in the database, and appended to the transaction description before the main LLM categorization call.

## Motivation

The local LLM (llama3) struggles with:
- Cryptic/truncated descriptions (e.g., `AMZN MKTP US*2K7XY`, `Ant*MoboreaderHongKongChinaHK`)
- Recognizable merchants whose business type isn't obvious to the model

Providing enriched context ("this is an online bookstore") before categorization significantly improves accuracy.

## Pipeline Integration

```
regex pre-pass → web enrichment (NEW) → LLM categorization
```

The enricher runs only on transactions that were NOT matched by the regex pre-pass. Results are cached so subsequent runs are instant for previously-seen merchants.

## Data Model

New table in `budget.db`: `merchant_cache`

| Column | Type | Purpose |
|--------|------|---------|
| `id` | INTEGER PK | Auto-increment |
| `description_pattern` | TEXT UNIQUE | Normalized description used as lookup key |
| `merchant_name` | TEXT | Clean merchant name from search results |
| `business_type` | TEXT | Short description of what the business does |
| `created_at` | TIMESTAMP | When the cache entry was created |

A `description_pattern` value of the normalized form allows similar transactions (e.g., same merchant at different locations) to share a single cache entry.

## WebEnricher Class

New module: `budget_parser/categorizer/web_enricher.py`

```python
class WebEnricher:
    def __init__(self, db_path: str, delay: float = 1.5, max_snippets: int = 3, model: str = "llama3"):
        ...

    def enrich(self, transactions: List[Dict]) -> List[Dict]:
        """For each uncategorized transaction:
        1. Normalize description → cache key
        2. Check merchant_cache table → if hit, attach context
        3. If miss → search DuckDuckGo → grab top snippets
        4. Summarize snippets via local LLM (5 words or fewer)
        5. Store in merchant_cache
        6. Attach context to transaction dict
        """
```

## Description Normalization

Before searching or checking the cache, descriptions are normalized:
- Strip trailing alphanumeric codes (e.g., `*2K7XY`)
- Remove common merchant prefixes (`TST*`, `SQ *`, `PP*`)
- Strip state abbreviations and zip codes
- Result is used as both search query and cache key

## Search & Parsing

1. Query DuckDuckGo with normalized description + "merchant" keyword
2. Scrape top 2-3 result snippets from HTML response (no API key)
3. Send snippets to local LLM with prompt: "Given these search results, what type of business is this? Reply in 5 words or fewer."
4. Cache the summarized result

## How Context Reaches the LLM

The `CategorizationAgent._build_prompt` currently sends:
```
0: AMZN MKTP US*2K7XY
```

With enrichment:
```
0: AMZN MKTP US*2K7XY (Context: Amazon Marketplace - online retail store)
```

The prompt structure stays the same — just richer input per line.

## Configuration

In `config.yaml`:

```yaml
web_enrichment:
  enabled: true
  search_delay: 1.5
  max_snippet_results: 3
  summarization_model: llama3
```

## CLI Flag

```
python -m budget_parser categorize --year 2025 --no-enrich
```

Bypasses web enrichment for fast/offline runs.

## Error Handling

- **Search fails** (network error, rate limit, timeout): log warning, skip enrichment for that transaction, LLM categorizes without context
- **No useful results**: cache a "no_result" entry to avoid re-searching
- **Summarization fails**: fall back to raw snippet text or skip

## Rate Limiting

Configurable delay between searches (default 1.5s). For 50 unknown merchants, ~75 seconds of search time — acceptable as a one-time cost since results are cached.

## Dependencies

- HTTP library for DuckDuckGo scraping (requests or httpx — already available or lightweight)
- HTML parsing (BeautifulSoup or similar) for extracting snippets
- No external API keys required
