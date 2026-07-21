"""Extract subcommand — processes PDFs for a given year."""

import logging
import sys
from datetime import datetime
from pathlib import Path

from budget_parser.config.settings import get_settings, reset_settings
from budget_parser.database.db import init_db
from budget_parser.processors.pipeline import Pipeline
from budget_parser.utils.logger import setup_logger


def add_parser(subparsers):
    p = subparsers.add_parser(
        "extract",
        help="Extract transactions from PDF statements",
        description="Extract and clean bank transactions from PDF statements",
    )
    p.add_argument("--year", type=int, help="Statement year (default: current year)")
    p.add_argument("--config", type=str, help="Path to config.yaml")
    p.add_argument("--db", type=str, default="budget.db", help="SQLite DB path (default: budget.db)")
    p.add_argument("--todo-folder", type=str, help="Folder containing PDFs (overrides config)")
    p.add_argument("--done-folder", type=str, help="Folder for processed PDFs (overrides config)")
    p.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level",
    )
    p.add_argument("--no-move", action="store_true", help="Don't move processed PDFs to done/")
    p.add_argument("--test", action="store_true", default=False, help="Use test.db, keep PDFs in todo/, DEBUG logging")
    p.set_defaults(func=extract_main)
    return p


def extract_main(args) -> int:
    year = args.year if args.year else datetime.now().year
    year_defaulted = not args.year

    reset_settings()
    config_path = Path(args.config) if args.config else None
    settings = get_settings(config_path)

    if args.test:
        if args.db == "budget.db":
            args.db = "test.db"
        args.no_move = True
        if not args.log_level:
            args.log_level = "DEBUG"

    if not args.test and args.db == "budget.db" and (Path.cwd() / "test.db").exists():
        print(
            "⚠ test.db exists — did you mean to use --test? Running against budget.db.",
            file=sys.stderr,
        )

    settings.todo_folder = f"{year}/{settings.todo_folder}"
    settings.done_folder = f"{year}/{settings.done_folder}"

    if args.todo_folder:
        settings.todo_folder = args.todo_folder
    if args.done_folder:
        settings.done_folder = args.done_folder
    if args.log_level:
        settings.log_level = args.log_level
    if args.no_move:
        settings.move_to_done = False

    setup_logger(
        name="budget_parser",
        log_level=settings.log_level,
        log_file=settings.log_file,
        max_bytes=settings.log_max_bytes,
        backup_count=settings.log_backup_count,
        console_output=True,
    )

    logger = logging.getLogger("budget_parser")
    if year_defaulted:
        logger.warning(
            f"--year not specified; defaulting to {year}. "
            "Pass --year explicitly to avoid ambiguity."
        )
    logger.info(f"Statement year: {year}")
    logger.info(f"Database: {args.db}")

    init_db(args.db)

    try:
        pipeline = Pipeline(settings, year=year, db_path=args.db)
        results = pipeline.run()
        if all(r.success for r in results):
            return 0
        elif any(r.success for r in results):
            return 1
        else:
            return 2
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        return 130
    except Exception as e:
        print(f"\nFatal error: {e}")
        return 1
