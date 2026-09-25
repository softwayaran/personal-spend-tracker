"""Base filter interface."""

from abc import ABC, abstractmethod
from typing import List

from budget_parser.core.models import Transaction


class BaseFilter(ABC):
    """Abstract base class for transaction filters."""

    @abstractmethod
    def filter(self, transactions: List[Transaction]) -> List[Transaction]:
        """
        Filter transactions based on specific criteria.

        Args:
            transactions: List of transactions to filter

        Returns:
            Filtered list of transactions
        """
        pass

    @abstractmethod
    def get_filter_name(self) -> str:
        """
        Get the name of this filter for logging.

        Returns:
            Filter name
        """
        pass

    @abstractmethod
    def should_filter(self, transaction: Transaction) -> bool:
        """
        Check if a transaction should be filtered out.

        Args:
            transaction: Transaction to check

        Returns:
            True if transaction should be filtered out, False otherwise
        """
        pass
