"""Generic keyword-based transaction filter."""

from typing import List

from budget_parser.core.models import Transaction
from budget_parser.filters.base import BaseFilter
from budget_parser.utils.logger import get_logger

logger = get_logger(__name__)


class KeywordFilter(BaseFilter):
    """Filters out transactions whose description matches any keyword (case-insensitive)."""

    def __init__(self, name: str, keywords: List[str]):
        self._name = name
        self.keywords = [kw.lower() for kw in keywords]

    def filter(self, transactions: List[Transaction]) -> List[Transaction]:
        filtered = []
        filtered_count = 0
        for trans in transactions:
            if self.should_filter(trans):
                logger.debug(f"Filtered ({self._name}): {trans.description[:50]}")
                filtered_count += 1
            else:
                filtered.append(trans)
        if filtered_count > 0:
            logger.info(f"{self._name}: Filtered {filtered_count} transactions")
        return filtered

    def should_filter(self, transaction: Transaction) -> bool:
        description_lower = transaction.description.lower()
        return any(kw in description_lower for kw in self.keywords)

    def get_filter_name(self) -> str:
        return self._name
