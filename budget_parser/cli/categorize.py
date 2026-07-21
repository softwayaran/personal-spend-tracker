"""Categorize subcommand — categorizes transactions using Ollama LLM."""

import sys
from datetime import datetime
from pathlib import Path

from budget_parser.categorizer.agent import CategorizationAgent
from budget_parser.categorizer.regex_categorizer import RegexCategorizer
from budget_parser.categorizer.web_enricher import WebEnricher
from budget_parser.config.settings import get_settings, reset_settings
from budget_parser.database.db import (
    bulk_update_transaction_categories,
    get_categories,
    get_regex_rules,
    get_transactions,
    get_uncategorized_transactions,
    init_db,
)
from budget_parser.utils.logger import get_logger, setup_logger


def add_parser(subparsers):
    p = subparsers.add_parser(
        "categorize",
        help="Categorize transactions using Ollama LLM",
        description="Categorize bank transactions. Reads uncategorized rows from DB and writes categories back.",
    )
    p.add_argument("--year", type=int, help="Statement year (default: current year)")
    p.add_argument("--config", type=str, help="Path to config.yaml")
    p.add_argument("--db", type=str, default="budget.db", help="SQLite DB path (default: budget.db)")
    p.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level",
    )
    p.add_argument(
        "--no-enrich",
        action="store_true",
        default=False,
        help="Skip web enrichment (for fast/offline runs)",
    )
    p.add_argument("--test", action="store_true", default=False, help="Use test.db and DEBUG logging")
    p.set_defaults(func=categorize_main)
    return p


def categorize_main(args) -> int:
    reset_settings()
    config_path = Path(args.config) if args.config else None
    settings = get_settings(config_path)

    if args.test:
        if args.db == "budget.db":
            args.db = "test.db"
        if args.log_level == "INFO":
            args.log_level = "DEBUG"

    if not args.test and args.db == "budget.db" and (Path.cwd() / "test.db").exists():
        print(
            "⚠ test.db exists — did you mean to use --test? Running against budget.db.",
            file=sys.stderr,
        )

    setup_logger(
        name="budget_parser",
        log_level=args.log_level,
        log_file=settings.log_file,
        max_bytes=settings.log_max_bytes,
        backup_count=settings.log_backup_count,
        console_output=True,
    )
    logger = get_logger("categorize")

    if args.year:
        year = args.year
    else:
        year = datetime.now().year
        logger.warning(
            f"--year not specified; defaulting to {year}. "
            "Pass --year explicitly to avoid ambiguity."
        )
    logger.info(f"Statement year: {year}")

    init_db(args.db)
    logger.info(f"Database: {args.db}")

    categories = get_categories(args.db)
    regex_rules = get_regex_rules(args.db, enabled_only=True)

    if not categories:
        logger.error("No categories in DB. Add category/sub-category pairs in the dashboard (Categories tab) and rerun.")
        return 1

    pending = get_uncategorized_transactions(args.db, year)
    if not pending:
        logger.info("Nothing to categorize — all transactions already have a category.")
        return 0

    logger.info(f"Found {len(pending)} uncategorized transaction(s).")

    if regex_rules:
        regex_cat = RegexCategorizer(regex_rules)
        pending = regex_cat.categorize(pending)
        regex_done = sum(1 for tx in pending if tx.get("category", "").strip())
        if regex_done:
            logger.info(f"Regex pre-pass categorized {regex_done} transaction(s)")

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

    agent = CategorizationAgent(
        model=settings.llm_model,
        categories=categories,
        temperature=settings.llm_temperature,
        top_p=settings.llm_top_p,
        num_predict=settings.llm_num_predict,
        batch_size=settings.categorize_batch_size,
    )
    results = agent.categorize(pending)

    categorized_results = [tx for tx in results if tx.get("category", "").strip() and tx.get("id")]
    updated = bulk_update_transaction_categories(args.db, categorized_results)
    logger.info(f"DB updated: {updated} transaction(s) categorized")

    all_txs = get_transactions(args.db, year)
    categorized_total = sum(1 for tx in all_txs if tx.get("category", "").strip())
    uncategorized_total = len(all_txs) - categorized_total
    logger.info(
        f"Summary: {categorized_total} categorized, {uncategorized_total} uncategorized"
        f" (total: {len(all_txs)})"
    )

    if uncategorized_total:
        logger.info(
            f"Tip: Add new category/sub-category pairs in the dashboard (Categories tab) "
            f"then rerun 'budget categorize --year {year}' to classify remaining transactions."
        )

    return 0
