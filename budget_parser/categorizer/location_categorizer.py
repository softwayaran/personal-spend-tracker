"""Location-based vacation categorizer."""

import re
from typing import Any, Dict, List, Optional

from budget_parser.utils.logger import get_logger

logger = get_logger(__name__)

US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC",
}

CA_PROVINCES = {
    "AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE",
    "QC", "SK", "YT",
}

ALL_CODES = US_STATES | CA_PROVINCES

_ONLINE_RE = re.compile(r"\.COM|WWW\.|/BILL|ONLINE", re.IGNORECASE)

# No word boundary before the capture — intentional to support glued codes like "KENTWOODMI".
# Merchant names ending in state codes (COSTCO→CO) are a known false-positive risk, mitigated
# by regex rules running first and confidence capped at 0.9.
_STATE_RE = re.compile(
    r"([A-Z]{2})"
    r"(?:\s*-?\s*\$[\d.,]+)?"
    r"\s*$"
)


class LocationCategorizer:
    """Categorize out-of-state transactions as Vacation."""

    def __init__(self, home_state: str):
        self._home_state = home_state.upper().strip()

    def _extract_state(self, description: str) -> Optional[str]:
        """Extract the state/province code from a transaction description.

        Returns the two-letter code if found and valid, else None.
        """
        m = _STATE_RE.search(description.strip())
        if m:
            code = m.group(1)
            if code in ALL_CODES:
                return code
        return None

    def categorize(self, transactions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Tag out-of-state transactions as Vacation.

        Skips already-categorized rows, online transactions, and
        home-state matches. Does nothing if home_state is empty.
        """
        if not self._home_state:
            return transactions

        results = [dict(tx) for tx in transactions]
        tagged = 0

        for tx in results:
            if tx.get("category", "").strip():
                continue

            desc = tx.get("description", "")

            if _ONLINE_RE.search(desc):
                continue

            state = self._extract_state(desc)
            if state and state != self._home_state:
                tx["category"] = "Vacation"
                tx["sub_category"] = ""
                tx["confidence"] = 0.9
                tx["categorized_by"] = "location"
                tagged += 1

        if tagged:
            logger.info(f"Location categorizer: tagged {tagged} out-of-state transaction(s) as Vacation")

        return results
