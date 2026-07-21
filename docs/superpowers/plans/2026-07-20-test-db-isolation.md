# Test Database Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `--test` CLI flag for dev runs against an isolated `test.db`, a safety warning when `test.db` exists, and a pytest fixture for ephemeral test databases.

**Architecture:** Three independent changes: (1) `--test` flag on `extract` and `categorize` CLIs that switches db path, disables file movement, and bumps log level, (2) a stderr warning when running without `--test` while `test.db` exists, (3) a `db_path` pytest fixture using `tmp_path`. All changes are additive — no existing behavior changes.

**Tech Stack:** Python, argparse, pytest, SQLite

---

### Task 1: Add `db_path` pytest fixture

**Files:**
- Modify: `tests/conftest.py`
- Test: `tests/test_core/test_db_fixture.py` (create)

- [ ] **Step 1: Write a test that uses the new `db_path` fixture**

Create `tests/test_core/test_db_fixture.py`:

```python
"""Verify the db_path fixture provides a working isolated database."""

from pathlib import Path

from budget_parser.database.db import get_connection, upsert_transactions, get_transactions


def test_db_path_fixture_creates_initialized_db(db_path):
    """Fixture should return a path to an existing, initialized SQLite DB."""
    assert Path(db_path).exists()
    conn = get_connection(db_path)
    try:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = sorted(r[0] for r in tables)
        assert "categories" in table_names
        assert "transactions" in table_names
        assert "regex_rules" in table_names
        assert "merchant_cache" in table_names
    finally:
        conn.close()


def test_db_path_fixture_is_isolated(db_path):
    """Each test should get its own empty DB — no data from other tests."""
    txs = get_transactions(db_path, 2025)
    assert txs == []


def test_db_path_fixture_is_writable(db_path):
    """Fixture DB should support normal read/write operations."""
    upsert_transactions(db_path, 2025, [
        {"date": "01/15", "description": "TEST STORE", "amount": 42.00},
    ])
    txs = get_transactions(db_path, 2025)
    assert len(txs) == 1
    assert txs[0]["description"] == "TEST STORE"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_core/test_db_fixture.py -v`
Expected: FAIL — `db_path` fixture not found

- [ ] **Step 3: Add the `db_path` fixture to `tests/conftest.py`**

Add the following import and fixture to `tests/conftest.py`, after the existing imports:

```python
from budget_parser.database.db import init_db
```

Add the fixture after the existing `cleanup_settings` fixture:

```python
@pytest.fixture
def db_path(tmp_path):
    """Ephemeral initialized SQLite DB for test isolation."""
    path = str(tmp_path / "test_budget.db")
    init_db(path)
    return path
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_core/test_db_fixture.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add tests/conftest.py tests/test_core/test_db_fixture.py
git commit -m "feat: add db_path pytest fixture for test isolation"
```

---

### Task 2: Add `--test` flag to `extract` CLI

**Files:**
- Modify: `budget_parser/cli/extract.py`
- Test: `tests/test_cli/test_extract_test_flag.py` (create)
- Create: `tests/test_cli/__init__.py`

- [ ] **Step 1: Write tests for the `--test` flag behavior**

Create `tests/test_cli/__init__.py` (empty file).

Create `tests/test_cli/test_extract_test_flag.py`:

```python
"""Tests for the --test flag on the extract CLI."""

import argparse
import sys
from pathlib import Path
from unittest.mock import patch

from budget_parser.cli.extract import add_parser


def _parse_extract_args(args: list[str]) -> argparse.Namespace:
    """Helper: parse args through the extract subparser."""
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers()
    add_parser(subs)
    return parser.parse_args(["extract"] + args)


def test_default_db_is_budget_db():
    """Without --test, db defaults to budget.db."""
    ns = _parse_extract_args(["--year", "2025"])
    assert ns.db == "budget.db"
    assert ns.test is False


def test_test_flag_sets_test_db():
    """--test should set db to test.db."""
    ns = _parse_extract_args(["--year", "2025", "--test"])
    assert ns.test is True


def test_explicit_db_with_test_flag():
    """Explicit --db should be accepted alongside --test."""
    ns = _parse_extract_args(["--year", "2025", "--test", "--db", "custom.db"])
    assert ns.db == "custom.db"
    assert ns.test is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_cli/test_extract_test_flag.py -v`
Expected: FAIL — `ns.test` attribute doesn't exist

- [ ] **Step 3: Add `--test` argument to `extract.py` `add_parser`**

In `budget_parser/cli/extract.py`, inside `add_parser`, add this line after the `--no-move` argument:

```python
p.add_argument("--test", action="store_true", default=False, help="Use test.db, keep PDFs in todo/, DEBUG logging")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_cli/test_extract_test_flag.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Write tests for `extract_main` behavior with `--test`**

Add to `tests/test_cli/test_extract_test_flag.py`:

```python
import logging
from unittest.mock import patch, MagicMock

from budget_parser.cli.extract import extract_main


def test_extract_main_test_flag_sets_db_path(tmp_path):
    """--test should make extract_main use test.db."""
    args = argparse.Namespace(
        year=2025,
        config=None,
        db="budget.db",
        test=True,
        todo_folder=None,
        done_folder=None,
        log_level=None,
        no_move=False,
    )
    with patch("budget_parser.cli.extract.Pipeline") as mock_pipeline, \
         patch("budget_parser.cli.extract.init_db") as mock_init:
        mock_pipeline.return_value.run.return_value = []
        extract_main(args)
        mock_init.assert_called_once_with("test.db")
        mock_pipeline.assert_called_once()
        _, kwargs = mock_pipeline.call_args
        assert kwargs["db_path"] == "test.db"


def test_extract_main_test_flag_explicit_db_wins(tmp_path):
    """Explicit --db should override --test's default."""
    args = argparse.Namespace(
        year=2025,
        config=None,
        db="custom.db",
        test=True,
        todo_folder=None,
        done_folder=None,
        log_level=None,
        no_move=False,
    )
    with patch("budget_parser.cli.extract.Pipeline") as mock_pipeline, \
         patch("budget_parser.cli.extract.init_db") as mock_init:
        mock_pipeline.return_value.run.return_value = []
        extract_main(args)
        mock_init.assert_called_once_with("custom.db")


def test_extract_main_test_flag_disables_move():
    """--test should disable file movement."""
    args = argparse.Namespace(
        year=2025,
        config=None,
        db="budget.db",
        test=True,
        todo_folder=None,
        done_folder=None,
        log_level=None,
        no_move=False,
    )
    with patch("budget_parser.cli.extract.Pipeline") as mock_pipeline, \
         patch("budget_parser.cli.extract.init_db"):
        mock_pipeline.return_value.run.return_value = []
        extract_main(args)
        mock_pipeline.assert_called_once()
        _, kwargs = mock_pipeline.call_args
        assert kwargs["db_path"] == "test.db"
```

- [ ] **Step 6: Run to verify the new tests fail**

Run: `pytest tests/test_cli/test_extract_test_flag.py -v`
Expected: The 3 new tests FAIL — `extract_main` doesn't handle `args.test` yet

- [ ] **Step 7: Implement `--test` logic in `extract_main`**

In `budget_parser/cli/extract.py`, in `extract_main`, add the following block right after `settings = get_settings(config_path)` (after line 41) and before the `settings.todo_folder` line:

```python
    # --test convenience: switch to test.db, disable move, bump to DEBUG
    if args.test:
        if args.db == "budget.db":
            args.db = "test.db"
        args.no_move = True
        if not args.log_level:
            args.log_level = "DEBUG"
```

Also add `import sys` at the top of the file (needed for safety warning in the next task).

- [ ] **Step 8: Run all tests to verify they pass**

Run: `pytest tests/test_cli/test_extract_test_flag.py -v`
Expected: All 6 tests PASS

- [ ] **Step 9: Commit**

```bash
git add budget_parser/cli/extract.py tests/test_cli/__init__.py tests/test_cli/test_extract_test_flag.py
git commit -m "feat: add --test flag to extract CLI for dev isolation"
```

---

### Task 3: Add `--test` flag to `categorize` CLI

**Files:**
- Modify: `budget_parser/cli/categorize.py`
- Test: `tests/test_cli/test_categorize_test_flag.py` (create)

- [ ] **Step 1: Write tests for the `--test` flag on categorize**

Create `tests/test_cli/test_categorize_test_flag.py`:

```python
"""Tests for the --test flag on the categorize CLI."""

import argparse

from budget_parser.cli.categorize import add_parser


def _parse_categorize_args(args: list[str]) -> argparse.Namespace:
    """Helper: parse args through the categorize subparser."""
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers()
    add_parser(subs)
    return parser.parse_args(["categorize"] + args)


def test_default_db_is_budget_db():
    """Without --test, db defaults to budget.db."""
    ns = _parse_categorize_args(["--year", "2025"])
    assert ns.db == "budget.db"
    assert ns.test is False


def test_test_flag_present():
    """--test flag should be accepted."""
    ns = _parse_categorize_args(["--year", "2025", "--test"])
    assert ns.test is True


def test_explicit_db_with_test_flag():
    """Explicit --db should be accepted alongside --test."""
    ns = _parse_categorize_args(["--year", "2025", "--test", "--db", "custom.db"])
    assert ns.db == "custom.db"
    assert ns.test is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_cli/test_categorize_test_flag.py -v`
Expected: FAIL — `ns.test` attribute doesn't exist

- [ ] **Step 3: Add `--test` argument to `categorize.py` `add_parser`**

In `budget_parser/cli/categorize.py`, inside `add_parser`, add this line after the `--no-enrich` argument:

```python
p.add_argument("--test", action="store_true", default=False, help="Use test.db and DEBUG logging")
```

- [ ] **Step 4: Run argparse tests to verify they pass**

Run: `pytest tests/test_cli/test_categorize_test_flag.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Write tests for `categorize_main` behavior with `--test`**

Add to `tests/test_cli/test_categorize_test_flag.py`:

```python
from unittest.mock import patch

from budget_parser.cli.categorize import categorize_main


def test_categorize_main_test_flag_sets_db_path():
    """--test should make categorize_main use test.db."""
    args = argparse.Namespace(
        year=2025,
        config=None,
        db="budget.db",
        test=True,
        log_level="INFO",
        no_enrich=True,
    )
    with patch("budget_parser.cli.categorize.init_db") as mock_init, \
         patch("budget_parser.cli.categorize.get_categories", return_value=[]), \
         patch("budget_parser.cli.categorize.get_uncategorized_transactions", return_value=[]):
        categorize_main(args)
        mock_init.assert_called_once_with("test.db")


def test_categorize_main_explicit_db_wins():
    """Explicit --db should override --test's default."""
    args = argparse.Namespace(
        year=2025,
        config=None,
        db="custom.db",
        test=True,
        log_level="INFO",
        no_enrich=True,
    )
    with patch("budget_parser.cli.categorize.init_db") as mock_init, \
         patch("budget_parser.cli.categorize.get_categories", return_value=[]), \
         patch("budget_parser.cli.categorize.get_uncategorized_transactions", return_value=[]):
        categorize_main(args)
        mock_init.assert_called_once_with("custom.db")
```

- [ ] **Step 6: Run to verify the new tests fail**

Run: `pytest tests/test_cli/test_categorize_test_flag.py -v`
Expected: The 2 new tests FAIL — `categorize_main` doesn't handle `args.test`

- [ ] **Step 7: Implement `--test` logic in `categorize_main`**

In `budget_parser/cli/categorize.py`, in `categorize_main`, add the following block right after `settings = get_settings(config_path)` (after line 50) and before `setup_logger`:

```python
    # --test convenience: switch to test.db, bump to DEBUG
    if args.test:
        if args.db == "budget.db":
            args.db = "test.db"
        if args.log_level == "INFO":
            args.log_level = "DEBUG"
```

- [ ] **Step 8: Run all tests to verify they pass**

Run: `pytest tests/test_cli/test_categorize_test_flag.py -v`
Expected: All 5 tests PASS

- [ ] **Step 9: Commit**

```bash
git add budget_parser/cli/categorize.py tests/test_cli/test_categorize_test_flag.py
git commit -m "feat: add --test flag to categorize CLI for dev isolation"
```

---

### Task 4: Add safety warning when `test.db` exists

**Files:**
- Modify: `budget_parser/cli/extract.py`
- Modify: `budget_parser/cli/categorize.py`
- Test: `tests/test_cli/test_safety_warning.py` (create)

- [ ] **Step 1: Write tests for the safety warning**

Create `tests/test_cli/test_safety_warning.py`:

```python
"""Tests for the safety warning when test.db exists."""

import argparse
import sys
from pathlib import Path
from unittest.mock import patch

from budget_parser.cli.extract import extract_main
from budget_parser.cli.categorize import categorize_main


def test_extract_warns_when_test_db_exists(tmp_path, capsys):
    """extract should warn on stderr when test.db exists and no --test/--db."""
    test_db = tmp_path / "test.db"
    test_db.touch()

    args = argparse.Namespace(
        year=2025,
        config=None,
        db="budget.db",
        test=False,
        todo_folder=None,
        done_folder=None,
        log_level=None,
        no_move=False,
    )
    with patch("budget_parser.cli.extract.Pipeline") as mock_pipeline, \
         patch("budget_parser.cli.extract.init_db"), \
         patch("budget_parser.cli.extract.Path.cwd", return_value=tmp_path):
        mock_pipeline.return_value.run.return_value = []
        extract_main(args)

    captured = capsys.readouterr()
    assert "test.db exists" in captured.err
    assert "--test" in captured.err


def test_extract_no_warning_when_test_db_absent(tmp_path, capsys):
    """No warning when test.db doesn't exist."""
    args = argparse.Namespace(
        year=2025,
        config=None,
        db="budget.db",
        test=False,
        todo_folder=None,
        done_folder=None,
        log_level=None,
        no_move=False,
    )
    with patch("budget_parser.cli.extract.Pipeline") as mock_pipeline, \
         patch("budget_parser.cli.extract.init_db"), \
         patch("budget_parser.cli.extract.Path.cwd", return_value=tmp_path):
        mock_pipeline.return_value.run.return_value = []
        extract_main(args)

    captured = capsys.readouterr()
    assert "test.db exists" not in captured.err


def test_extract_no_warning_with_test_flag(tmp_path, capsys):
    """No warning when --test is used, even if test.db exists."""
    test_db = tmp_path / "test.db"
    test_db.touch()

    args = argparse.Namespace(
        year=2025,
        config=None,
        db="budget.db",
        test=True,
        todo_folder=None,
        done_folder=None,
        log_level=None,
        no_move=False,
    )
    with patch("budget_parser.cli.extract.Pipeline") as mock_pipeline, \
         patch("budget_parser.cli.extract.init_db"), \
         patch("budget_parser.cli.extract.Path.cwd", return_value=tmp_path):
        mock_pipeline.return_value.run.return_value = []
        extract_main(args)

    captured = capsys.readouterr()
    assert "test.db exists" not in captured.err


def test_extract_no_warning_with_explicit_db(tmp_path, capsys):
    """No warning when --db is explicitly set."""
    test_db = tmp_path / "test.db"
    test_db.touch()

    args = argparse.Namespace(
        year=2025,
        config=None,
        db="custom.db",
        test=False,
        todo_folder=None,
        done_folder=None,
        log_level=None,
        no_move=False,
    )
    with patch("budget_parser.cli.extract.Pipeline") as mock_pipeline, \
         patch("budget_parser.cli.extract.init_db"), \
         patch("budget_parser.cli.extract.Path.cwd", return_value=tmp_path):
        mock_pipeline.return_value.run.return_value = []
        extract_main(args)

    captured = capsys.readouterr()
    assert "test.db exists" not in captured.err


def test_categorize_warns_when_test_db_exists(tmp_path, capsys):
    """categorize should warn on stderr when test.db exists and no --test/--db."""
    test_db = tmp_path / "test.db"
    test_db.touch()

    args = argparse.Namespace(
        year=2025,
        config=None,
        db="budget.db",
        test=False,
        log_level="INFO",
        no_enrich=True,
    )
    with patch("budget_parser.cli.categorize.init_db"), \
         patch("budget_parser.cli.categorize.get_categories", return_value=[]), \
         patch("budget_parser.cli.categorize.Path.cwd", return_value=tmp_path):
        categorize_main(args)

    captured = capsys.readouterr()
    assert "test.db exists" in captured.err
    assert "--test" in captured.err


def test_categorize_no_warning_with_test_flag(tmp_path, capsys):
    """No warning when --test is used."""
    test_db = tmp_path / "test.db"
    test_db.touch()

    args = argparse.Namespace(
        year=2025,
        config=None,
        db="budget.db",
        test=True,
        log_level="INFO",
        no_enrich=True,
    )
    with patch("budget_parser.cli.categorize.init_db"), \
         patch("budget_parser.cli.categorize.get_categories", return_value=[]), \
         patch("budget_parser.cli.categorize.Path.cwd", return_value=tmp_path):
        categorize_main(args)

    captured = capsys.readouterr()
    assert "test.db exists" not in captured.err
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_cli/test_safety_warning.py -v`
Expected: FAIL — no warning logic exists yet

- [ ] **Step 3: Add safety warning to `extract_main`**

In `budget_parser/cli/extract.py`, add `import sys` at the top if not already present.

In `extract_main`, add the following block right after the `--test` convenience block (after the `if args.test:` block) and before `setup_logger`:

```python
    # Safety warning: nudge if test.db exists but user isn't using --test
    if not args.test and args.db == "budget.db" and (Path.cwd() / "test.db").exists():
        print(
            "⚠ test.db exists — did you mean to use --test? Running against budget.db.",
            file=sys.stderr,
        )
```

- [ ] **Step 4: Add safety warning to `categorize_main`**

In `budget_parser/cli/categorize.py`, add `import sys` at the top.

In `categorize_main`, add the following block right after the `--test` convenience block and before `setup_logger`:

```python
    # Safety warning: nudge if test.db exists but user isn't using --test
    if not args.test and args.db == "budget.db" and (Path.cwd() / "test.db").exists():
        print(
            "⚠ test.db exists — did you mean to use --test? Running against budget.db.",
            file=sys.stderr,
        )
```

- [ ] **Step 5: Run all tests to verify they pass**

Run: `pytest tests/test_cli/test_safety_warning.py -v`
Expected: All 7 tests PASS

- [ ] **Step 6: Run the full test suite**

Run: `pytest -v`
Expected: All tests PASS (no regressions)

- [ ] **Step 7: Commit**

```bash
git add budget_parser/cli/extract.py budget_parser/cli/categorize.py tests/test_cli/test_safety_warning.py
git commit -m "feat: add safety warning when test.db exists without --test flag"
```

---

### Task 5: Add `test.db` to `.gitignore`

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Add `test.db` to `.gitignore`**

Append to `.gitignore`:

```
# Test database (created by --test flag)
test.db
```

- [ ] **Step 2: Commit**

```bash
git add .gitignore
git commit -m "chore: add test.db to gitignore"
```
