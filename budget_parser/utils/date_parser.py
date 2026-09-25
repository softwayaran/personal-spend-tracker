"""Date parsing helpers for statement-style transaction dates."""

from datetime import date
import re
from typing import Optional, Tuple


_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}


def _is_valid_month_day(month: int, day: int) -> bool:
    """Validate month/day with a leap-safe year."""
    try:
        date(2000, month, day)
        return True
    except ValueError:
        return False


def parse_statement_date(date_str: str) -> Optional[Tuple[int, int]]:
    """
    Parse statement date into (month, day).

    Supported examples:
    - 1/2, 01/02, 01/02/25, 01/02/2025
    - 2025-01-02
    - Jan 2, Jan. 2, January 2, Jan 2 2025, January 2, 2025
    - 2 Jan, 2 January
    """
    if not isinstance(date_str, str):
        return None

    raw = " ".join(date_str.strip().replace(",", " ").split())
    if not raw:
        return None

    # MM/DD or MM/DD/YY or MM/DD/YYYY
    m = re.match(r"^(\d{1,2})/(\d{1,2})(?:/\d{2,4})?$", raw)
    if m:
        month = int(m.group(1))
        day = int(m.group(2))
        return (month, day) if _is_valid_month_day(month, day) else None

    # MM-DD or MM-DD-YY or MM-DD-YYYY
    m = re.match(r"^(\d{1,2})-(\d{1,2})(?:-\d{2,4})?$", raw)
    if m:
        month = int(m.group(1))
        day = int(m.group(2))
        return (month, day) if _is_valid_month_day(month, day) else None

    # YYYY-MM-DD
    m = re.match(r"^\d{4}-(\d{1,2})-(\d{1,2})$", raw)
    if m:
        month = int(m.group(1))
        day = int(m.group(2))
        return (month, day) if _is_valid_month_day(month, day) else None

    # Month DD [YYYY]
    m = re.match(r"^([A-Za-z]{3,9}\.?)\s+(\d{1,2})(?:\s+\d{2,4})?$", raw)
    if m:
        token = m.group(1).rstrip(".").lower()
        day = int(m.group(2))
        month = _MONTHS.get(token)
        if month and _is_valid_month_day(month, day):
            return month, day
        return None

    # DD Month [YYYY]
    m = re.match(r"^(\d{1,2})\s+([A-Za-z]{3,9}\.?)\s*(?:\d{2,4})?$", raw)
    if m:
        day = int(m.group(1))
        token = m.group(2).rstrip(".").lower()
        month = _MONTHS.get(token)
        if month and _is_valid_month_day(month, day):
            return month, day
        return None

    return None


def normalize_statement_date(date_str: str) -> Optional[str]:
    """Normalize supported date string to MM/DD."""
    parsed = parse_statement_date(date_str)
    if not parsed:
        return None
    month, day = parsed
    return f"{month:02d}/{day:02d}"

