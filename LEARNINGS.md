# Learnings: personal-spend-tracker (`budget-parser`)

> Persistent notes on this codebase. Read fully before working here. Keep it current: update it
> as you learn more or as the code changes, and don't let it go stale. `CLAUDE.md` covers commands
> and the pipeline steps. This file covers what that one doesn't: why things are built this way,
> the sharp edges, and where CLAUDE.md or the README is wrong.
>
> Written 2026-09-25 from code analysis alone. The author gave no extra context.

## Overview
A single-user, local-first personal finance tool. It turns credit-card/bank statement PDFs into
categorized transactions in a SQLite DB (`budget.db`) and shows them in a Streamlit dashboard.
The LLM work runs on a local Ollama model. It's published at `github.com/softwayaran/personal-spend-tracker`,
and the README was rewritten for a public release on 2026-05-30.

## Tech Stack
- Python ≥3.9 (setuptools package `budget_parser`, console script `budget`), venv in `myenv/`
- pdfplumber (PDF text), `ollama` client (extraction, categorization, summarization), pydantic v2 + pydantic-settings
- SQLite through the stdlib `sqlite3` (WAL mode). There's no ORM.
- Streamlit ≥1.35 + Plotly (dashboard), pandas
- `duckduckgo-search` (web enrichment). `httpx` is still listed but looks unused since commit 3caa12c.
- Dev: pytest (+cov and html by default through `addopts`), ruff, black (line length 100), mypy

## Architecture Summary
There are three subcommands, all behind `budget_parser/cli/main.py` (argparse, with each module registering
its own subparser through `add_parser`): `extract`, `categorize`, `serve`. They share no state except
`budget.db`, which sits relative to the CWD. **Always run from the repo root.** `config.yaml`, `logs/`,
`YYYY/todo` and `budget.db` are all CWD-relative.

**extract**: `Pipeline` (`processors/pipeline.py`) runs once per PDF in `YYYY/todo/`. pdfplumber splits it into
30-line chunks. `LLMExtractor` (Ollama, `format=json`) extracts transactions, and `TransactionValidator`
drops any it can't find in the chunk text (the anti-hallucination step). If an LLM chunk validates to 0,
`RegexExtractor` runs on it. Then comes the keyword filter chain, then `infer_years`, then
`upsert_transactions` (INSERT OR IGNORE), then the PDF moves to `done/`. An error in one PDF is caught
and returned as `ProcessingResult(success=False)`, and that PDF stays in `todo/`.

**categorize**: loads the uncategorized rows for `--year`. Then:
1. The regex pre-pass (`RegexCategorizer`, rules stored in the DB) runs.
2. The web enrichment pass (`WebEnricher`) sends a DuckDuckGo search for the normalized description, gets a
   5-word Ollama summary, caches it in `merchant_cache`, and attaches it as `context`.
3. `CategorizationAgent` sends batches of 20 to Ollama, restricted to the category pairs in the DB. It uses
   local 0-based indices so partial or reordered responses map back correctly, and it retries missing
   items one at a time.
4. `bulk_update_transaction_categories` writes the results.

Rows that already have a category are never touched, which is what makes reruns safe.

**serve**: `subprocess` runs `streamlit run dashboard/app.py`. The dashboard (821 lines, the biggest file) has
5 tabs (Overview, MoM, Transactions CRUD, Categories CRUD, Regex Rules CRUD). It uses `st.cache_data`
keyed on a `db_version` session counter, and every write bumps that counter to bust the cache.

## Key Files
| File | Role | Notes |
|------|------|-------|
| `budget_parser/database/db.py` | Every SQL statement and the schema (`init_db`) | Schema changes use `CREATE TABLE IF NOT EXISTS` only. There are **no migrations**, so a column added here won't reach an existing `budget.db`. |
| `budget_parser/processors/pipeline.py` | The extract orchestrator | Swallows per-PDF exceptions and only logs them |
| `budget_parser/cli/categorize.py` | The categorize orchestrator | Holds the pass ordering (regex, then enrich, then LLM) |
| `budget_parser/categorizer/agent.py` | Categorization prompt + batch/retry logic | The prompt hard-codes the author's own category names in its hints/examples (Restaurants, Grocery, Car/Gas…) |
| `budget_parser/categorizer/web_enricher.py` | DuckDuckGo + LLM merchant context | Makes network calls. See Risks. |
| `budget_parser/validators/transaction_validator.py` | 4-strategy check that an extraction appears in the source text | This is the main defense against LLM-invented rows |
| `budget_parser/utils/date_utils.py` | `infer_years` handles the Dec/Jan boundary | Heuristic, per PDF batch |
| `budget_parser/config/settings.py` | pydantic Settings + a module-level singleton | Call `reset_settings()` before `get_settings()`. Both CLIs already do. |
| `budget_parser/dashboard/app.py` | Streamlit UI | `DEFAULT_DB_PATH = "budget.db"` is hard-coded, so it can't view `test.db` |
| `config.yaml` (gitignored) | The live config | The shipped fallback is `budget_parser/config/default_config.yaml` |

## Design Decisions (the "why")
- **Local LLM only (Ollama)** is meant to keep financial data off the cloud (README: "Privacy by design").
  *Web enrichment partly breaks this* because it sends merchant descriptions to DuckDuckGo. It's on by
  default, and `--no-enrich` or `web_enrichment_enabled: false` turns it off. The README claim hasn't been updated.
- **Categories and regex rules live in the DB, not in config.** That way the dashboard is the single editing
  surface (CLAUDE.md and the config comments say so). `config.yaml` holds only LLM params, filter keywords and paths.
- **Dates stay `MM/DD` until DB insert.** Statements carry no year, so the year comes from `--year`
  plus the boundary heuristic in `infer_years`. The `transactions.year` column is the *statement* year and can
  differ from the year in `date`: a Jan-2026 statement's Dec rows get `date=2025-12-xx, year=2026`. Every
  dashboard and categorize query filters on `year`, not `date`.
- **Dedup key is `UNIQUE(year, date, description, amount)`** with INSERT OR IGNORE. This makes re-extracting
  the same PDF idempotent.
- **Regex before LLM** keeps results fast and deterministic, with first match winning. Rules are user-curated
  in the dashboard.
- **Local 0-based batch indices plus per-item retry** in `CategorizationAgent` came from commit 16e5c99. The
  small model sometimes returned fewer items, or a single dict instead of an array, and
  `normalize_ai_output` handles the single-dict case.
- **`--test` flag** (design spec `docs/superpowers/specs/2026-07-20-test-db-isolation-design.md`) exists
  because dev runs with dummy PDFs were polluting the real `budget.db`. `--test` means `test.db`, no PDF
  move, and DEBUG logging. An explicit `--db` wins. Without `--test`, the CLI warns when `test.db` exists.
- **The Superpowers workflow**: features arrive as a spec plus a plan under `docs/superpowers/` and then
  small conventional commits. Follow that pattern for new features.
- **History / provenance** (inferred): this repo is a cleaned-up public copy of
  `../ai-apps/personal-budget-tool` (the older sibling in the parent folder, whose last commits are "remove private
  files"). The two copies have since diverged: web enrichment exists only here.

## Coupling / Blast Radius
- `db.py` is imported by the pipeline, both CLIs, the enricher and the dashboard. Renaming a function or changing a
  dict key (`category`, `sub_category`, `merchant`, `id`, `context`) breaks every one of them. Transactions
  travel as plain dicts after DB load and as the `Transaction` pydantic model only during extraction.
- `Settings` field names are also the YAML keys and the `BUDGET_PARSER_*` env var names. Renaming a field silently
  orphans the user's `config.yaml` key, because `extra="ignore"` means no error is raised.
- The categorize CLI mutates `settings.todo_folder`/`done_folder` in place (prefixing the year) on the
  singleton. That's harmless per process, but it's why `reset_settings()` matters in tests and scripts.
- Category renames (`update_category`) cascade to transactions by string match, while `delete_category`
  does **not** cascade, which leaves transactions with orphaned category strings.
- `merchant_cache` keys come from `normalize_description`, so changing those regexes invalidates cache hits
  (old rows stay, but new keys differ).

## Risks & Fragile Areas
- **Most of the package wasn't committed until 2026-09-25.** Before branch `chore/track-source-files`
  (commit 87c9bbf), only about 10 of the ~35 source files were tracked. The repo had been initialized
  mid-project. `main` and GitHub still lack them until that branch is merged. New files have to be
  `git add`ed explicitly, so check `git status` for `??` entries.
- **Keyword filters are plain substring matches** (`kw in description.lower()`). Keywords like `pts`,
  `points`, `miles`, `total`, `balance` and `purchases` will silently drop real purchases (e.g. "TOTAL WINE",
  "RECEIPTS", "MILES KIMBALL"). Nothing logs a dropped row at INFO level, so you'd only notice missing data.
- **Dedup collapses genuine duplicates**: two identical same-day, same-amount purchases become one row.
- **Web enrichment caches failures permanently**: a search exception returns `[]`, so `"no_result"` is
  cached and never retried. A network outage during one run poisons those merchants. The fix is to delete rows
  from `merchant_cache`.
- **Env vars do NOT override YAML**, despite what CLAUDE.md and the README say. `Settings.from_yaml` passes YAML values
  as init kwargs, and pydantic-settings ranks init kwargs above env vars. `BUDGET_PARSER_*` only takes effect for
  keys absent from `config.yaml`. Verified 2026-09-25: with `BUDGET_PARSER_LLM_MODEL=envmodel` set,
  `from_yaml` still returns `llama3`.
- **Model defaults disagree**: `settings.py` defaults `llm_model` to `gemma4`, while `config.yaml`, the README and
  `web_enrichment_model` use `llama3`. That only matters when there's no config file, but it's surprising.
- **No tests** cover `pipeline.py`, `llm_extractor.py`, `pdf_extractor.py`, `agent.categorize` batching,
  `date_utils.infer_years`, `db.update_category` cascade, or the dashboard. Tests that exist mock Ollama and DDGS.
- **The year-boundary heuristic** only fires when months 1–3 *and* 10–12 appear in the same PDF. A Dec-only
  statement filed under the next year's folder gets the wrong year.
- **No schema migrations**: see `db.py` above.
- **Stray junk in the repo root**: an empty directory literally named
  `C:Users<user>sourcerepos…personal-spend-trackerteststest_categorizer` (a mangled Windows path from
  some earlier command), an empty `.open` file, and `2026/*.csv` files left over from the pre-DB CSV era. The
  directory and `.open` are safe to delete, and the CSVs are gitignored.

## How to Run / Test / Build
- Setup: `python -m venv myenv && source myenv/Scripts/activate && pip install -e ".[dev]"`. Ollama must be
  running with the configured model (`ollama pull llama3`).
- Run: `python -m budget_parser extract --year 2026` → `python -m budget_parser categorize --year 2026` →
  `python -m budget_parser serve`. Add `--test` to extract/categorize for scratch runs against `test.db`.
  Add `--no-enrich` for offline runs.
- Test: `pytest` (70 tests, ~2 s, all passing on 2026-09-25; no Ollama or network needed). `--no-cov` skips the
  coverage/htmlcov output.
- Lint: `ruff check budget_parser/`, `black budget_parser/`, `mypy budget_parser/`
- The `db_path` fixture in `tests/conftest.py` gives a fresh temp DB. Use it rather than touching `budget.db`.

## Open Questions
- Merge `chore/track-source-files` (on top of `feat/test-db-isolation`) into `main` and push.
- Should web enrichment default to **off**, given the README's privacy promise?
- Is `../ai-apps/personal-budget-tool` abandoned, or are the two kept in sync?
- Can `httpx` and `docs/architecture.md` (which omits web enrichment) be dropped or updated?

## Session Log
- 2026-09-25 (later): Scanned the untracked files for personal data and found none (the sample transactions don't
  match `budget.db`). Replaced real merchant names in the `agent.py` prompt examples and the normalizer test with
  generic ones. Committed all untracked source on `chore/track-source-files`. A fresh clone passes all 70 tests.
  The "Grand Rapids" sample strings were left in the tests, extractor prompt and `conftest.py`.
- 2026-09-25: First pass, written from code analysis alone. Read the CLIs, pipeline, settings, db, agent and
  enricher, and ran the test suite (70 passed). Found the untracked-source problem, the env-var precedence
  error in the docs, substring filter false positives, and permanent caching of enrichment failures.
