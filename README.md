# Personal Spend Tracker

[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

A local-first personal finance tool that extracts transactions from bank statement PDFs, categorizes them with AI, and displays everything in an interactive dashboard. **Your data never leaves your machine.**

<!-- TODO: Add a screenshot of the dashboard here -->
<!-- ![Dashboard Screenshot](docs/images/dashboard.png) -->

## Features

- **PDF extraction** — drop bank statement PDFs into a folder, run one command, and get structured transaction data
- **Fast AI categorization** — uses [laya](https://laya.convaiinnovations.com/), a local classifier that categorizes transactions in ~33ms each with calibrated confidence scores
- **Five-tier pipeline** — regex rules, location-based vacation detection, laya classifier, LLM fallback, and manual review work together so nothing slips through
- **Location-based vacation detection** — transactions outside your home state are automatically tagged as Vacation, so trip spending shows up without manual tagging
- **Confidence scoring** — every categorization carries a confidence score (color-coded in the dashboard) so you can spot and fix uncertain results
- **Web enrichment** — optionally searches the web for merchant context to improve LLM fallback accuracy
- **Interactive dashboard** — Streamlit-powered UI with spending charts, drill-downs, transaction editing, and category management
- **Anti-hallucination validation** — multi-strategy verification ensures extracted transactions actually exist in the source PDF
- **Privacy by design** — everything runs locally; no cloud APIs, no data sharing

## Getting Started

This section covers everything you need to install and run the tool.

### Prerequisites

- [Python 3.9+](https://www.python.org/downloads/)
- [Ollama](https://ollama.com/download) with a language model (used for PDF extraction and as a categorization fallback)

```bash
# Install Ollama, then pull a model (~4 GB, one-time download)
ollama pull gemma4
```

Laya (the primary categorizer) is installed automatically with the package. On first run, it downloads its model checkpoint (~808 MB) from HuggingFace — this is a one-time download that takes a few minutes depending on your connection.

### Installation

```bash
git clone https://github.com/softwayaran/personal-spend-tracker.git
cd personal-spend-tracker
pip install -e .
```

Verify the install:

```bash
python -m budget_parser --help
```

### Usage

The tool runs as a three-step pipeline:

```bash
# 1. Drop PDFs into 2026/todo/, then extract transactions
python -m budget_parser extract --year 2026

# 2. Categorize extracted transactions
python -m budget_parser categorize --year 2026

# 3. Open the interactive dashboard
python -m budget_parser serve
```

#### Year-folder layout

```
2026/
  todo/    <-- drop PDFs here before running extract
  done/    <-- processed PDFs are moved here automatically
```

All data is stored in `budget.db` (SQLite). The `--year` flag scopes which folder to scan and helps resolve dates that lack a year (most bank statements show MM/DD only).

## Configuration

`config.yaml` in the project root controls runtime behavior. All values can be overridden with environment variables prefixed `BUDGET_PARSER_` (e.g., `BUDGET_PARSER_LLM_MODEL=llama3`).

| Key | Default | Description |
|---|---|---|
| `llm_model` | `gemma4` | Ollama model for extraction and LLM fallback categorization |
| `llm_temperature` | `0.1` | Lower = more consistent results |
| `llm_top_p` | `0.2` | Lower = more focused answers |
| `llm_num_predict` | `3000` | Max tokens per LLM request |
| `lines_per_chunk` | `30` | Lines of PDF text per LLM call |
| `enable_regex_fallback` | `true` | Try regex if LLM finds nothing during extraction |
| `categorize_batch_size` | `20` | Transactions per LLM categorization batch |
| `home_state` | `MI` | Two-letter state code; transactions outside this state are tagged as Vacation |
| `laya_model` | `convaiinnovations/laya` | HuggingFace model checkpoint for laya |
| `laya_confidence_threshold` | `0.6` | Below this confidence, transactions fall back to the LLM |
| `laya_enabled` | `true` | Set to `false` to skip laya and use only the LLM for categorization |
| `log_level` | `INFO` | Use `DEBUG` for troubleshooting |

Categories and regex rules are managed in `budget.db` via the dashboard, not in `config.yaml`.

## CLI Reference

```bash
# Extract transactions from PDFs
python -m budget_parser extract --year 2026
python -m budget_parser extract --year 2026 --no-move    # don't move PDFs to done/

# Categorize transactions
python -m budget_parser categorize --year 2026
python -m budget_parser categorize --year 2026 --no-enrich  # skip web enrichment

# Launch dashboard
python -m budget_parser serve
python -m budget_parser serve --port 8080
```

## Troubleshooting

| Problem | Solution |
|---|---|
| `'budget' is not recognized` (Windows) | Use `python -m budget_parser` instead |
| Dashboard shows no data | Run `extract` and `categorize` first |
| `No PDF files found` | Ensure PDFs are in `<year>/todo/`, not `<year>/` |
| Ollama connection refused | Start Ollama: run `ollama serve` or launch from Start menu |
| Wrong/extra transactions extracted | Works best with text-based PDFs (not scanned images) |
| First `categorize` run is slow | Laya downloads its model (~808 MB) on first use — subsequent runs are fast |
| Laya model download fails | Check your internet connection; the model is fetched from HuggingFace. Retry the command once the connection is stable |
| Want to skip laya entirely | Set `laya_enabled: false` in `config.yaml` to revert to LLM-only categorization |
| Online orders tagged as Vacation | Add a regex rule for that merchant in the dashboard (regex runs before location detection) |

---

## Development

This section is for developers working on or debugging the codebase.

### How It Works

#### Stage 1 — Extract

```
PDF files in <year>/todo/
  -> PDFExtractor          splits PDF into text chunks
  -> LLMExtractor          sends chunks to Ollama, returns transactions as JSON
  -> TransactionValidator   verifies transactions exist in source text
                            (exact -> normalized -> substring -> fuzzy match)
  -> RegexExtractor        fallback if LLM returns nothing for a chunk
  -> KeywordFilter         removes rewards/payment/aggregate lines (3 passes)
  -> upsert_transactions   writes to budget.db (INSERT OR IGNORE, safe to rerun)
  -> FileManager           moves PDF to <year>/done/
```

#### Stage 2 — Categorize

A five-tier waterfall pipeline. Each tier only processes transactions left uncategorized by the previous one:

```
budget.db (uncategorized rows for the year)
  |
  v
Tier 1: RegexCategorizer     fast pre-pass using regex rules from budget.db
  |                           confidence = 1.0, categorized_by = "regex"
  v
Tier 1.5: LocationCategorizer out-of-state transactions -> Vacation
  |                           confidence = 0.9, categorized_by = "location"
  v
Tier 2: LayaCategorizer       two-step laya classification (category -> sub_category)
  |                           confidence >= 0.6 -> accept (categorized_by = "laya")
  |                           confidence < 0.6  -> route to tier 3
  v
Tier 3: WebEnricher + LLM     web enrichment (optional) + Ollama LLM fallback
  |                           categorized_by = "llm"
  v
Tier 4: Best-guess store      laya's low-confidence guess stored for manual review
  |                           visible in dashboard with confidence score
  v
MerchantExtractor             regex-based merchant name cleaning for all rows
```

Already-categorized rows (including manual edits from the dashboard) are never overwritten.

#### Stage 3 — Dashboard

A Streamlit + Plotly web app with five tabs:

| Tab | Purpose |
|---|---|
| **Monthly Overview** | Spending charts by category, laya stats card (method counts + avg confidence) |
| **Month-over-Month** | Trend comparison across months |
| **Transactions** | Full transaction list with confidence (color-coded), categorized_by badges, inline editing |
| **Categories** | Manage category/sub-category pairs and their descriptions (used as laya criteria) |
| **Regex Rules** | Add pattern rules (e.g., `NETFLIX` -> Utilities/Streaming) |

The sidebar includes a **categorized_by** filter to view transactions by classification method (regex, location, laya, llm, manual). Manual edits in the Transactions tab stamp `categorized_by = "manual"` and clear the confidence score.

### Setup

```bash
git clone https://github.com/softwayaran/personal-spend-tracker.git
cd personal-spend-tracker

python -m venv myenv

# Activate the virtual environment
source myenv/Scripts/activate    # Windows (Git Bash)
myenv\Scripts\activate.bat       # Windows (Command Prompt)
source myenv/bin/activate        # macOS / Linux

pip install -e ".[dev]"
```

### Project Structure

```
personal-spend-tracker/
├── budget_parser/
│   ├── cli/                  # CLI entry points (extract, categorize, serve)
│   ├── core/                 # Transaction model (Pydantic)
│   ├── extractors/           # PDF text extraction + LLM/regex extractors
│   ├── validators/           # Anti-hallucination transaction validation
│   ├── filters/              # Keyword filters (rewards, payments, aggregates)
│   ├── processors/           # Pipeline orchestration
│   ├── categorizer/          # Categorization engine
│   │   ├── laya_categorizer.py   # Two-step laya classification
│   │   ├── merchant_extractor.py # Regex-based merchant name cleaning
│   │   ├── regex_categorizer.py  # Regex pre-pass
│   │   ├── agent.py              # LLM fallback (Ollama)
│   │   └── web_enricher.py       # DuckDuckGo merchant context
│   ├── database/             # SQLite operations (no ORM)
│   ├── file_manager/         # PDF file movement (todo -> done)
│   ├── config/               # Settings (Pydantic) + default config
│   ├── utils/                # Logging, text processing, date utilities
│   └── dashboard/            # Streamlit app (5 tabs)
├── tests/                    # Test suite (pytest)
├── config.yaml               # Local configuration
├── budget.db                 # SQLite database (created on first run)
└── pyproject.toml            # Package metadata + tool config
```

### Testing and Code Quality

```bash
pytest                      # full test suite with coverage
pytest --no-cov -q          # fast run without coverage
pytest -k "test_filter"     # run tests matching a pattern

ruff check budget_parser/   # lint
black budget_parser/        # format
mypy budget_parser/         # type-check
```

### Key Design Decisions

- **Laya two-step classification** — 45 category/sub-category pairs across 15 top-level categories. Laya's accuracy degrades above ~20 options, so classification uses two sequential `choice` calls: first picks the category (15 options), then picks the sub-category (2-6 options). Confidence = min(step 1, step 2).
- **`Transaction.date` stays MM/DD** throughout the pipeline. Year inference runs at DB insert time via `date_utils.infer_years()`.
- **Settings singleton** — `get_settings()` returns a cached instance. Call `reset_settings()` before `get_settings()` in scripts so CLI overrides take effect.
- **Filters** share a `BaseFilter` interface — add new filters by subclassing and inserting into `Pipeline.__init__`.
- **Web enrichment** results are cached in a `merchant_cache` table to avoid redundant searches across runs.
- **DB migrations** — `ALTER TABLE ADD COLUMN` wrapped in try/except for idempotent upgrades. No migration framework; the schema self-heals on `init_db()`.

## Tech Stack

| Package | Role |
|---|---|
| [laya](https://laya.convaiinnovations.com/) | Primary transaction categorizer (~33ms, calibrated confidence) |
| [pdfplumber](https://github.com/jsvine/pdfplumber) | PDF text extraction |
| [Ollama](https://ollama.com) | Local LLM inference (extraction + categorization fallback) |
| [Pydantic](https://docs.pydantic.dev) | Data validation and settings |
| [Streamlit](https://streamlit.io) | Dashboard framework |
| [Plotly](https://plotly.com/python/) | Interactive charts |
| [DuckDuckGo Search](https://pypi.org/project/duckduckgo-search/) | Merchant web enrichment |
| [pandas](https://pandas.pydata.org) | Data manipulation |

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Make your changes and add tests
4. Ensure all tests pass (`pytest`)
5. Run linting and formatting (`ruff check budget_parser/ && black budget_parser/`)
6. Commit your changes and open a pull request

## License

This project is licensed under the MIT License. See [pyproject.toml](pyproject.toml) for details.
