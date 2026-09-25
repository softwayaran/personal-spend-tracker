"""Date utilities for year inference and ISO date formatting."""

from typing import List

from budget_parser.core.models import Transaction
from budget_parser.utils.date_parser import parse_statement_date


def infer_years(transactions: List[Transaction], statement_year: int) -> List[str]:
    """
    Infer full YYYY-MM-DD date for each transaction.

    Bank statements use MM/DD format with no year. When a statement spans a
    year boundary (e.g. a January statement containing December transactions),
    months 10-12 are assigned statement_year - 1 and months 1-3 get statement_year.

    Args:
        transactions: List of Transaction objects with MM/DD dates
        statement_year: The year of the statement (from --year CLI arg)

    Returns:
        List of ISO date strings (YYYY-MM-DD) in the same order as input
    """
    parsed_dates = []
    for tx in transactions:
        parsed = parse_statement_date(tx.date)
        if not parsed:
            raise ValueError(f"Unsupported transaction date format: {tx.date}")
        parsed_dates.append(parsed)

    months = [month for month, _ in parsed_dates]

    # Detect year boundary: both early months (Jan–Mar) and late months (Oct–Dec) present
    early = any(m in range(1, 4) for m in months)
    late = any(m in range(10, 13) for m in months)
    has_boundary = early and late

    dates = []
    for (month, day) in parsed_dates:
        if has_boundary and month in range(10, 13):
            year = statement_year - 1
        else:
            year = statement_year
        dates.append(f"{year:04d}-{month:02d}-{day:02d}")

    return dates
