# Personal Spend Tracker

[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

A local-first personal finance tool that extracts transactions from bank statement PDFs, categorizes them with AI, and displays everything in an interactive dashboard. **Your data never leaves your machine.**

<!-- TODO: Add a screenshot of the dashboard here -->
<!-- ![Dashboard Screenshot](docs/images/dashboard.png) -->

## Features

- **PDF extraction** — drop bank statement PDFs into a folder, run one command, and get structured transaction data
- **AI-powered categorization** — uses a local LLM (via [Ollama](https://ollama.com)) to categorize transactions, with regex rules for speed and consistency
- **Web enrichment** — optionally searches the web for merchant context to improve categorization accuracy
- **Interactive dashboard** — Streamlit-powered UI with spending charts, drill-downs, transaction editing, and category management
- **Anti-hallucination validation** — multi-strategy verification ensures extracted transactions actually exist in the source PDF
- **Privacy by design** — everything runs locally with Ollama; no cloud APIs, no data sharing

## Quick Start

### Prerequisites

- [Python 3.9+](https://www.python.org/downloads/)
- [Ollama](https://ollama.com/download) with the `llama3` model

```bash
# Install Ollama, then pull the model (~4 GB, one-time download)
ollama pull llama3
```

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

## How It Works

### Stage 1 — Extract

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

### Stage 2 — Categorize

```
budget.db (uncategorized rows for the year)
  -> RegexCategorizer      fast pre-pass using regex rules from budget.db
  -> WebEnricher           searches DuckDuckGo for merchant context (optional)
  -> CategorizationAgent   sends remaining rows to Ollama in batches
  -> bulk update           writes categories back to budget.db
```

Already-categorized rows (including manual edits from the dashboard) are never overwritten.

### Stage 3 — Dashboard

A Streamlit + Plotly web app with five tabs:

| Tab | Purpose |
|---|---|
| **Monthly Overview** | Spending charts by category for a selected year/month |
| **Month-over-Month** | Trend comparison across months |
| **Transactions** | Full transaction list with inline editing |
| **Categories** | Manage category/sub-category pairs |
| **Regex Rules** | Add pattern rules (e.g., `NETFLIX` -> Utilities/Streaming) |

## Configuration

`config.yaml` in the project root controls runtime behavior. All values can be overridden with environment variables prefixed `BUDGET_PARSER_` (e.g., `BUDGET_PARSER_LLM_MODEL=llama3.2`).

| Key | Default | Description |
|---|---|---|
| `llm_model` | `llama3` | Ollama model for extraction and categorization |
| `llm_temperature` | `0.1` | Lower = more consistent results |
| `llm_top_p` | `0.2` | Lower = more focused answers |
| `llm_num_predict` | `3000` | Max tokens per LLM request |
| `lines_per_chunk` | `30` | Lines of PDF text per LLM call |
| `enable_regex_fallback` | `true` | Try regex if LLM finds nothing |
| `categorize_batch_size` | `20` | Transactions per categorization batch |
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

## Development

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
│   ├── categorizer/          # LLM categorization + regex pre-pass + web enrichment
│   ├── database/             # SQLite operations (no ORM)
│   ├── file_manager/         # PDF file movement (todo -> done)
│   ├── config/               # Settings (Pydantic) + default config
│   ├── utils/                # Logging, text processing, date utilities
│   └── dashboard/            # Streamlit app (5 tabs)
├── tests/                    # Test suite (pytest)
├── config.yaml               # Local configuration
├── budget.db                  # SQLite database (created on first run)
└── pyproject.toml             # Package metadata + tool config
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

- **`Transaction.date` stays MM/DD** throughout the pipeline. Year inference runs at DB insert time via `date_utils.infer_years()`.
- **Settings singleton** — `get_settings()` returns a cached instance. Call `reset_settings()` before `get_settings()` in scripts so CLI overrides take effect.
- **Filters** share a `BaseFilter` interface — add new filters by subclassing and inserting into `Pipeline.__init__`.
- **Web enrichment** results are cached in a `merchant_cache` table to avoid redundant searches across runs.

## Troubleshooting

| Problem | Solution |
|---|---|
| `'budget' is not recognized` (Windows) | Use `python -m budget_parser` instead |
| Dashboard shows no data | Run `extract` and `categorize` first |
| `No PDF files found` | Ensure PDFs are in `<year>/todo/`, not `<year>/` |
| Ollama connection refused | Start Ollama: run `ollama serve` or launch from Start menu |
| Wrong/extra transactions extracted | Works best with text-based PDFs (not scanned images) |

## Tech Stack

| Package | Role |
|---|---|
| [pdfplumber](https://github.com/jsvine/pdfplumber) | PDF text extraction |
| [Ollama](https://ollama.com) | Local LLM inference |
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
