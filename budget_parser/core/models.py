"""Data models for budget parser."""

from typing import Any
from pydantic import BaseModel, field_validator, ConfigDict

from budget_parser.utils.date_parser import normalize_statement_date


class Transaction(BaseModel):
    """
    Represents a single financial transaction.

    Attributes:
        date: Transaction date normalized to MM/DD
        description: Transaction description/merchant name
        amount: Transaction amount (positive for debits, negative for credits)
    """
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True
    )

    date: str
    description: str
    amount: float

    @field_validator('date')
    @classmethod
    def validate_date_format(cls, v: str) -> str:
        """Validate and normalize supported statement date formats to MM/DD."""
        if not isinstance(v, str):
            raise ValueError(f"Date must be a string, got {type(v)}")

        v = v.strip()
        normalized = normalize_statement_date(v)
        if not normalized:
            raise ValueError(f"Date must be in a supported format, got: {v}")

        return normalized

    @field_validator('description')
    @classmethod
    def validate_description(cls, v: str) -> str:
        """Validate description is not empty."""
        if not isinstance(v, str):
            raise ValueError(f"Description must be a string, got {type(v)}")

        v = v.strip()
        if not v:
            raise ValueError("Description cannot be empty")

        return v

    @field_validator('amount', mode='before')
    @classmethod
    def validate_amount(cls, v: Any) -> float:
        """Validate amount is a valid number and not zero."""
        if isinstance(v, str):
            # Clean the string (remove $, commas)
            v = v.replace('$', '').replace(',', '').strip()

        try:
            amount = float(v)
        except (ValueError, TypeError):
            raise ValueError(f"Amount must be a valid number, got: {v}")

        if amount == 0:
            raise ValueError("Amount cannot be zero")

        return amount
