# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Workflow Orchestration

### 1. Plan Mode Default
- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions)
- If something goes sideways, STOP and re-plan immediately - don't keep pushing
- Use plan mode for verification steps, not just building
- Write detailed specs upfront to reduce ambiguity

### 2. Subagent Strategy
- Use subagents liberally to keep main context window clean
- Offload research, exploration, and parallel analysis to subagents
- For complex problems, throw more compute at it via subagents
- One tack per subagent for focused execution

### 3. Self-Improvement Loop
- After ANY correction from the user: update `tasks/lessons.md` with the pattern
- Write rules for yourself that prevent the same mistake
- Ruthlessly iterate on these lessons until mistake rate drops
- Review lessons at session start for relevant project

### 4. Verification Before Done
- Never mark a task complete without proving it works
- Diff behavior between main and your changes when relevant
- Ask yourself: "Would a staff engineer approve this?"
- Run tests, check logs, demonstrate correctness

### 5. Demand Elegance (Balanced)
- For non-trivial changes: pause and ask "is there a more elegant way?"
- If a fix feels hacky: "Knowing everything I know now, implement the elegant solution"
- Skip this for simple, obvious fixes - don't over-engineer
- Challenge your own work before presenting it

### 6. Autonomous Bug Fixing
- When given a bug report: just fix it. Don't ask for hand-holding
- Point at logs, errors, failing tests - then resolve them
- Zero context switching required from the user
- Go fix failing CI tests without being told how

## Task Management

1. **Plan First**: Write plan to `tasks/todo.md` with checkable items
2. **Verify Plan**: Check in before starting implementation
3. **Track Progress**: Mark items complete as you go
4. **Explain Changes**: High-level summary at each step
5. **Document Results**: Add review section to `tasks/todo.md`
6. **Capture Lessons**: Update `tasks/lessons.md` after corrections

## Core Principles

- **Simplicity First**: Make every change as simple as possible. Impact minimal code.
- **No Laziness**: Find root causes. No temporary fixes. Senior developer standards.
- **Minimat Impact**: Changes should only touch what's necessary. Avoid introducing bugs.

### App Related
## Environment

```bash
source myenv/Scripts/activate   # Windows bash — must prefix every command
```

Requires Ollama running locally with llama3: `ollama serve` / `ollama pull llama3`.

## Common Commands

```bash
# Step 1 — Extract transactions from PDFs into budget.db
python -m budget_parser extract --year 2025

# Step 2 — Categorize uncategorized transactions in budget.db
python -m budget_parser categorize --year 2025

# Dashboard
python -m budget_parser serve

# Lint / format / type-check
ruff check budget_parser/
black budget_parser/
mypy budget_parser/

# Tests
pytest                                      # all tests
pytest tests/test_core/test_models.py       # single file
pytest -k "test_validate"                   # by name
```

## Year-Folder Workflow

All data is scoped to a year folder. The `--year` argument is required (defaults to current year with a warning).

```
2025/
  todo/          ← drop PDFs here before running extraction
  done/          ← processed PDFs moved here automatically
```

The year prefix is **applied at runtime** by the CLI — `config.yaml` values (`todo_folder`, `done_folder`) are subfolder names only, not full paths. Transactions are stored in `budget.db`, not in year-scoped CSVs.

## Architecture

### Two-stage pipeline

**Stage 1 — Extraction** (`python -m budget_parser extract --year YYYY`):

`cli/extract.py` → loads settings → `Pipeline` → for each PDF:
1. `PDFExtractor` splits PDF into text chunks
2. `LLMExtractor` (Ollama) extracts `Transaction` objects from each chunk
3. `TransactionValidator` verifies extracted transactions exist in source text (4-strategy anti-hallucination: exact → normalized → substring → fuzzy word match)
4. If LLM yields nothing and `enable_regex_fallback=true`, `RegexExtractor` runs instead
5. Three `KeywordFilter` instances run in chain (rewards → payment → aggregate keywords)
6. `date_utils.infer_years()` converts MM/DD dates to YYYY-MM-DD, then `upsert_transactions` writes to `budget.db`
7. `FileManager` moves the PDF to `done/`

**Stage 2 — Categorization** (`python -m budget_parser categorize --year YYYY`):

Reads uncategorized transactions from `budget.db` (rows with empty `category` for the given year).

1. **Regex pre-pass** (`RegexCategorizer`): matches `description` against regex rules from `budget.db` (case-insensitive, first-match wins). Matched rows skip the LLM entirely.
2. **LLM pass** (`CategorizationAgent`): sends remaining uncategorized rows to Ollama in batches. Uses `format="json"` + local index mapping to handle partial/reordered responses.

**Rerun workflow**: add categories or regex rules via the dashboard → `python -m budget_parser categorize --year YYYY` — already-categorized rows are preserved untouched.

### Key design details

- **`Transaction.date` stays MM/DD** throughout the pipeline. Year inference (`date_utils.infer_years`) runs at DB insert time. Year boundary detection: if both months 1–3 and 10–12 appear in the same batch, months 10–12 get `statement_year - 1`.
- **Settings singleton**: `get_settings()` returns a cached instance. Always call `reset_settings()` before `get_settings()` in scripts (already done in both CLIs) so CLI overrides aren't stale between runs.
- **Filters** share a `BaseFilter` interface (`budget_parser/filters/base.py`) — add new filters by subclassing and inserting into the `self.filters` list in `Pipeline.__init__`.
- **`config.yaml`** is the source of truth for LLM params and filter keywords. Categories and regex rules are managed exclusively in `budget.db` (via the dashboard). Environment variables prefixed `BUDGET_PARSER_` override any config setting.

### Dashboard (`budget_parser/dashboard/app.py`)

Streamlit + Plotly app that reads from `budget.db`. Year is selected from the sidebar (auto-detected via `get_available_years()`). Uses `st.session_state` keys `ov_cat`, `ov_month`, `ov_sub` for drill-down state in Tab 1. Use `width='stretch'` (not `use_container_width=True`) for `st.plotly_chart` and `st.dataframe` — Streamlit 1.35+ deprecates the old parameter.
