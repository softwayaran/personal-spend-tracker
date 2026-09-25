"""Regex-based transaction categorizer (runs before LLM as a fast pre-pass)."""

import re
from typing import Any, Dict, List

from budget_parser.utils.logger import get_logger

logger = get_logger(__name__)


class RegexCategorizer:
    """
    Categorizes transactions by matching description against configured regex patterns.

    Rules are evaluated in order; the first match wins. Already-categorized
    transactions (rerun mode) are skipped.
    """

    def __init__(self, rules: List[Dict[str, Any]]):
        """
        Args:
            rules: List of dicts with keys: pattern, category, sub_category, merchant
        """
        self._rules = []
        for rule in rules:
            try:
                self._rules.append({
                    "pattern": re.compile(rule["pattern"], re.IGNORECASE),
                    "category": rule["category"],
                    "sub_category": rule["sub_category"],
                    "merchant": rule["merchant"],
                })
            except re.error as e:
                logger.warning(f"Invalid regex pattern '{rule['pattern']}': {e} — skipping rule")

    def categorize(self, transactions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Apply regex rules to uncategorized transactions.

        Args:
            transactions: List of transaction dicts (may include already-categorized rows)

        Returns:
            Same list with regex-matched rows filled in
        """
        if not self._rules:
            return transactions

        results = [dict(tx) for tx in transactions]
        applied = 0

        for tx in results:
            if tx.get("category", "").strip():
                continue  # already categorized — skip
            description = tx.get("description", "")
            for rule in self._rules:
                if rule["pattern"].search(description):
                    tx["category"] = rule["category"]
                    tx["sub_category"] = rule["sub_category"]
                    tx["merchant"] = rule["merchant"]
                    applied += 1
                    break

        if applied:
            logger.info(f"Regex categorizer: matched {applied} transaction(s)")

        return results
