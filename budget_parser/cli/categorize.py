"""Categorize subcommand — four-tier categorization pipeline."""

import sys
from datetime import datetime
from pathlib import Path

from budget_parser.categorizer.agent import CategorizationAgent
from budget_parser.categorizer.laya_categorizer import LayaCategorizer
from budget_parser.categorizer.location_categorizer import LocationCategorizer
from budget_parser.categorizer.merchant_extractor import MerchantExtractor
from budget_parser.categorizer.regex_categorizer import RegexCategorizer
from budget_parser.categorizer.web_enricher import WebEnricher
from budget_parser.config.settings import get_settings, reset_settings
from budget_parser.database.db import (
    auto_populate_category_descriptions,
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
        help="Categorize transactions using laya + LLM fallback",
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

    # Auto-populate empty category descriptions for laya criteria
    populated = auto_populate_category_descriptions(args.db)
    if populated:
        logger.info(f"Auto-populated {populated} empty category description(s)")

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

    # ---- Tier 1: Regex pre-pass ----
    if regex_rules:
        regex_cat = RegexCategorizer(regex_rules)
        pending = regex_cat.categorize(pending)
        regex_done = [tx for tx in pending if tx.get("category", "").strip()]
        if regex_done:
            for tx in regex_done:
                tx["confidence"] = 1.0
                tx["categorized_by"] = "regex"
            logger.info(f"Regex pre-pass categorized {len(regex_done)} transaction(s)")

    # Save regex results immediately
    regex_results = [tx for tx in pending if tx.get("categorized_by") == "regex"]
    if regex_results:
        bulk_update_transaction_categories(args.db, regex_results)

    # ---- Tier 1.5: Location-based vacation detection ----
    still_pending = [tx for tx in pending if not tx.get("category", "").strip()]

    if still_pending and settings.home_state:
        location_cat = LocationCategorizer(settings.home_state)
        still_pending = location_cat.categorize(still_pending)

        location_done = [tx for tx in still_pending if tx.get("categorized_by") == "location"]
        if location_done:
            bulk_update_transaction_categories(args.db, location_done)
            logger.info(f"Location categorizer: {len(location_done)} out-of-state transaction(s) -> Vacation")

    # ---- Tier 2: Laya classification ----
    still_pending = [tx for tx in still_pending if not tx.get("category", "").strip()]

    if still_pending and settings.laya_enabled:
        laya_cat = LayaCategorizer(
            categories,
            model=settings.laya_model,
            confidence_threshold=settings.laya_confidence_threshold,
        )
        still_pending = laya_cat.categorize(still_pending)

        laya_done = [tx for tx in still_pending if tx.get("categorized_by") == "laya"]
        if laya_done:
            bulk_update_transaction_categories(args.db, laya_done)
            logger.info(f"Laya categorized {len(laya_done)} transaction(s)")

    # ---- Tier 3: Web enrichment + LLM fallback ----
    llm_pending = [tx for tx in still_pending if not tx.get("category", "").strip()]

    if llm_pending:
        if settings.web_enrichment_enabled and not args.no_enrich:
            enricher = WebEnricher(
                db_path=args.db,
                delay=settings.web_enrichment_delay,
                max_snippets=settings.web_enrichment_max_snippets,
                model=settings.web_enrichment_model,
            )
            llm_pending = enricher.enrich(llm_pending)
            enriched_count = sum(1 for tx in llm_pending if tx.get("context"))
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
        llm_results = agent.categorize(llm_pending)

        llm_done = [tx for tx in llm_results if tx.get("category", "").strip() and tx.get("id")]
        for tx in llm_done:
            tx["categorized_by"] = "llm"
        if llm_done:
            bulk_update_transaction_categories(args.db, llm_done)
            logger.info(f"LLM fallback categorized {len(llm_done)} transaction(s)")

    # ---- Tier 4: Store laya best guesses for remaining uncategorized ----
    final_pending = [
        tx for tx in (llm_results if llm_pending else still_pending)
        if not tx.get("category", "").strip() and tx.get("_laya_best_guess")
    ]
    if final_pending:
        for tx in final_pending:
            guess = tx["_laya_best_guess"]
            tx["category"] = guess["category"]
            tx["sub_category"] = guess["sub_category"]
            tx["confidence"] = guess["confidence"]
            tx["categorized_by"] = "laya"
        bulk_update_transaction_categories(args.db, final_pending)
        logger.info(f"Stored {len(final_pending)} low-confidence best guess(es) for review")

    # ---- Merchant extraction pass ----
    all_txs = get_transactions(args.db, year)
    merchant_extractor = MerchantExtractor()
    needs_merchant = [tx for tx in all_txs if not tx.get("merchant", "").strip()]
    if needs_merchant:
        merchant_updates = []
        for tx in needs_merchant:
            merchant = merchant_extractor.extract(tx["description"])
            if merchant:
                merchant_updates.append({
                    "id": tx["id"],
                    "category": tx.get("category", ""),
                    "sub_category": tx.get("sub_category", ""),
                    "merchant": merchant,
                    "confidence": tx.get("confidence"),
                    "categorized_by": tx.get("categorized_by"),
                })
        if merchant_updates:
            bulk_update_transaction_categories(args.db, merchant_updates)
            logger.info(f"Merchant extraction: filled {len(merchant_updates)} merchant name(s)")

    # ---- Summary ----
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
