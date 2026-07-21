# Test Database Isolation

**Date:** 2026-07-20
**Status:** Approved

## Problem

Running the extract or categorize pipeline with test/dummy PDFs writes directly into `budget.db`, overwriting or polluting real transaction data. There is no built-in way to isolate dev/test runs from production data.

## Solution

A `--test` convenience flag on the CLI plus a pytest fixture for automated test isolation.

## Design

### 1. `--test` CLI flag (manual dev runs)

Add `--test` to both `extract` and `categorize` subcommands.

**When `--test` is set:**
- `--db` defaults to `test.db` instead of `budget.db`
- `--no-move` is implied (PDFs stay in `todo/` for reuse)
- Log level defaults to `DEBUG` (unless `--log-level` is explicitly passed)

**Precedence:** An explicit `--db` always wins over `--test`. Passing `--test --db custom.db` uses `custom.db`.

**Files changed:** `budget_parser/cli/extract.py`, `budget_parser/cli/categorize.py`

**Example usage:**
```bash
python -m budget_parser extract --year 2025 --test
python -m budget_parser categorize --year 2025 --test
```

### 2. Safety warning

When running `extract` or `categorize` **without** `--test` and **without** an explicit `--db`:
- Check if `test.db` exists in the current directory
- If it does, print a warning to stderr:
  `⚠ test.db exists — did you mean to use --test? Running against budget.db.`

This is a non-blocking warning — the command proceeds normally against `budget.db`. It acts as a gentle reminder if the user has been doing dev runs and forgot to switch.

**Files changed:** `budget_parser/cli/extract.py`, `budget_parser/cli/categorize.py`

### 3. Pytest `db_path` fixture (automated tests)

Add a `db_path` fixture in `tests/conftest.py`:

```python
@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test_budget.db")
    init_db(path)
    return path
```

**Behavior:**
- Creates a fresh, fully initialized SQLite database in a temporary directory
- Each test gets its own isolated DB — no cross-test contamination
- Automatically cleaned up by pytest's `tmp_path` after the test session
- Existing tests that don't need a database are unaffected

**Files changed:** `tests/conftest.py`

## Out of Scope

- Dashboard (`serve`) changes — the dashboard is for real data; test data can be inspected with any SQLite browser
- Environment-variable profiles (`BUDGET_PARSER_ENV`)
- Separate config files for test mode

## Testing

- Unit test: `--test` flag sets db to `test.db`, disables file move, sets DEBUG logging
- Unit test: explicit `--db` overrides `--test`
- Unit test: safety warning triggers when `test.db` exists and no `--test`/`--db` given
- Integration test: `db_path` fixture provides a working, isolated database
