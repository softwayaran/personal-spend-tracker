"""Transaction validation to prevent LLM hallucinations."""

import re
from typing import List, Dict, Any

from budget_parser.core.models import Transaction
from budget_parser.utils.logger import get_logger
from budget_parser.utils.text_utils import parse_amount
from budget_parser.utils.date_parser import normalize_statement_date

logger = get_logger(__name__)


class TransactionValidator:
    """
    Validates extracted transactions against source text to prevent hallucinations.

    Uses multiple matching strategies with increasing flexibility:
    1. Exact match (description exists exactly in source)
    2. Normalized match (without special characters)
    3. Substring match (handles multi-line descriptions)
    4. Word-based fuzzy match (significant portion of words exist)
    """

    def validate(self, transactions: List[Dict[str, Any]], source_text: str) -> List[Transaction]:
        """
        Validate transactions against source text.

        Args:
            transactions: List of raw transaction dictionaries
            source_text: Source text to validate against

        Returns:
            List of validated Transaction objects
        """
        validated = []
        source_lower = source_text.lower()
        source_normalized = re.sub(r'[^a-z0-9\s]', '', source_lower)
        source_no_spaces = source_normalized.replace(' ', '').replace('\n', '').replace('\r', '')

        for trans in transactions:
            result = self._validate_single_transaction(
                trans,
                source_lower,
                source_normalized,
                source_no_spaces
            )

            if result:
                validated.append(result)

        logger.info(f"Validated {len(validated)}/{len(transactions)} transactions")
        return validated

    def _validate_single_transaction(
        self,
        trans: Dict[str, Any],
        source_lower: str,
        source_normalized: str,
        source_no_spaces: str
    ) -> Transaction:
        """
        Validate a single transaction using multiple strategies.

        Args:
            trans: Transaction dictionary
            source_lower: Lowercased source text
            source_normalized: Normalized source text (no special chars)
            source_no_spaces: Normalized source with no spaces

        Returns:
            Validated Transaction object or None if invalid
        """
        # Check required fields
        if not isinstance(trans, dict):
            return None

        if 'date' not in trans or 'description' not in trans or 'amount' not in trans:
            logger.debug(f"Missing required fields: {trans}")
            return None

        date = str(trans['date']).strip()
        description = str(trans['description']).strip()
        amount = trans['amount']

        # Skip empty values
        if not date or not description or amount == "":
            return None

        # Validate and normalize date format to MM/DD
        normalized_date = normalize_statement_date(date)
        if not normalized_date:
            logger.debug(f"Invalid date format: {date}")
            return None

        # Parse and validate amount
        amount_val = parse_amount(amount)
        if amount_val == 0:
            logger.debug(f"Zero amount for: {description}")
            return None

        # Normalize description for matching
        desc_normalized = re.sub(r'[^a-z0-9\s]', '', description.lower())
        desc_words = [w for w in desc_normalized.split() if len(w) > 2]

        # Strategy 1: Exact match
        if self._exact_match(description.lower(), source_lower):
            logger.debug(f"Exact match: {description[:40]}")
            return self._create_transaction(normalized_date, description, amount_val)

        # Strategy 2: Normalized match (without special chars)
        if self._normalized_match(desc_normalized, source_normalized):
            logger.debug(f"Normalized match: {description[:40]}")
            return self._create_transaction(normalized_date, description, amount_val)

        # Strategy 2b: Normalized match without spaces (handles LLM joining multi-line descriptions)
        if self._substring_match(desc_normalized, source_no_spaces):
            logger.debug(f"Substring match: {description[:40]}")
            return self._create_transaction(normalized_date, description, amount_val)

        # Strategy 3: Fuzzy word-based match
        if self._fuzzy_word_match(desc_words, source_lower, source_normalized):
            logger.debug(f"Fuzzy word match: {description[:40]}")
            return self._create_transaction(normalized_date, description, amount_val)

        # Transaction rejected - log details
        self._log_rejection(description, desc_normalized, desc_words, source_no_spaces, source_normalized)
        return None

    def _exact_match(self, description: str, source: str) -> bool:
        """Check if description exists exactly in source."""
        return description in source

    def _normalized_match(self, desc_normalized: str, source_normalized: str) -> bool:
        """Check if normalized description exists in normalized source."""
        return desc_normalized in source_normalized

    def _substring_match(self, desc_normalized: str, source_no_spaces: str) -> bool:
        """
        Check if significant substring of description exists in source.

        Handles cases where amount appears between merchant name and location in source.
        """
        desc_no_spaces = desc_normalized.replace(' ', '').replace('\n', '').replace('\r', '')

        # Full match without spaces
        if len(desc_no_spaces) >= 5 and desc_no_spaces in source_no_spaces:
            return True

        # Check if first 15 characters exist (significant prefix)
        if len(desc_no_spaces) >= 15:
            desc_prefix = desc_no_spaces[:15]
            if desc_prefix in source_no_spaces:
                return True

        return False

    def _fuzzy_word_match(self, desc_words: List[str], source_lower: str, source_normalized: str) -> bool:
        """
        Check if significant portion of description words exist in source.

        Accepts if at least 50% of words match (or all words if only 1-2 words).
        """
        if len(desc_words) < 1:
            return False

        matches = sum(1 for word in desc_words if word in source_normalized)
        required_matches = max(1, min(2, len(desc_words) // 2))

        return matches >= required_matches

    def _create_transaction(self, date: str, description: str, amount: float) -> Transaction:
        """
        Create validated Transaction object.

        Args:
            date: Transaction date
            description: Transaction description
            amount: Transaction amount

        Returns:
            Transaction object or None if validation fails
        """
        try:
            return Transaction(
                date=date,
                description=description,
                amount=amount
            )
        except Exception as e:
            logger.warning(f"Failed to create Transaction: {str(e)}")
            return None

    def _log_rejection(
        self,
        description: str,
        desc_normalized: str,
        desc_words: List[str],
        source_no_spaces: str,
        source_normalized: str
    ):
        """Log details about rejected transaction."""
        logger.debug(f"REJECTED: {description[:60]}")

        desc_no_spaces = desc_normalized.replace(' ', '').replace('\n', '').replace('\r', '')
        logger.debug(f"   desc_no_spaces: '{desc_no_spaces[:60]}'")

        if len(desc_no_spaces) >= 15:
            desc_prefix = desc_no_spaces[:15]
            prefix_found = desc_prefix in source_no_spaces
            logger.debug(f"   prefix (first 15 chars): '{desc_prefix}' - Found: {prefix_found}")

        logger.debug(f"   desc_words: {desc_words}")

        if len(desc_words) >= 1:
            matches = sum(1 for word in desc_words if word in source_normalized)
            logger.debug(f"   word matches: {matches}/{len(desc_words)}")
