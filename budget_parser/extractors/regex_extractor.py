"""Regex-based transaction extraction (fallback method)."""

import re
from typing import List, Dict, Any

from budget_parser.utils.logger import get_logger

logger = get_logger(__name__)


class RegexExtractor:
    """Extracts transactions using regex patterns (fallback when LLM fails)."""

    DATE_PATTERN = (
        r'(?:\d{1,2}[/-]\d{1,2}(?:/\d{2,4})?|'  # 11/07, 11-07, 11/07/2025
        r'[A-Za-z]{3,9}\.?\s+\d{1,2}(?:,\s*\d{2,4})?)'  # Jan 22, January 22, Jan. 22, 2025
    )

    # Multiple patterns to handle different bank statement formats
    PATTERNS = [
        # Date, description, amount (supports numeric and month-name dates)
        rf'^(?P<date>{DATE_PATTERN})\s+(?P<description>.+?)\s+\$?(?P<amount>[-]?\d+(?:,\d{{3}})*(?:\.\d{{2}})?)\s*$',
    ]

    # Keywords to skip (likely headers or non-transactions)
    SKIP_KEYWORDS = [
        'purchase', 'payment', 'credit', 'account activity', 'total', 'balance'
    ]

    def extract(self, chunk: str) -> List[Dict[str, Any]]:
        """
        Extract transactions from text chunk using regex patterns.

        Args:
            chunk: Text chunk to process

        Returns:
            List of transaction dictionaries
        """
        transactions = []
        lines = chunk.split('\n')

        for line in lines:
            line = line.strip()
            if not line:
                continue

            transaction = self._extract_from_line(line)
            if transaction:
                transactions.append(transaction)

        logger.info(f"Regex extracted {len(transactions)} transactions from chunk")
        return transactions

    def _extract_from_line(self, line: str) -> Dict[str, Any]:
        """
        Try to extract transaction from a single line using multiple patterns.

        Args:
            line: Text line to parse

        Returns:
            Transaction dictionary or None if no match
        """
        for pattern in self.PATTERNS:
            match = re.match(pattern, line)
            if match:
                date = match.group("date")
                description = match.group("description").strip()
                amount_str = match.group("amount").replace(',', '').replace('$', '')

                # Skip if description is too short (likely a header)
                if len(description) < 3:
                    continue

                # Skip if description looks like a header
                desc_lower = description.lower()
                if any(keyword == desc_lower for keyword in self.SKIP_KEYWORDS):
                    continue

                try:
                    amount = float(amount_str)

                    # Skip zero amounts
                    if amount == 0:
                        continue

                    logger.debug(f"Regex matched: {date} {description[:30]} {amount}")

                    return {
                        "date": date,
                        "description": description,
                        "amount": amount
                    }

                except ValueError:
                    continue

        return None
