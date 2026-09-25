"""Custom exceptions for the budget parser package."""


class BudgetParserError(Exception):
    """Base exception for all budget parser errors."""
    pass


class PDFExtractionError(BudgetParserError):
    """Raised when PDF text extraction fails."""
    pass
