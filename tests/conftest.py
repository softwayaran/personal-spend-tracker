"""Pytest configuration and fixtures."""

import pytest
from typing import List, Dict, Any

from budget_parser.core.models import Transaction
from budget_parser.config.settings import Settings, reset_settings
from budget_parser.database.db import init_db


@pytest.fixture
def sample_transactions() -> List[Transaction]:
    """Sample valid transactions for testing."""
    return [
        Transaction(date="11/07", description="MEIJER STORE #158", amount=113.76),
        Transaction(date="11/08", description="SQ *FRIENDS OF THE LIBRAR", amount=2.00),
        Transaction(date="11/10", description="AMAZON.COM", amount=45.99),
    ]


@pytest.fixture
def sample_transaction_dicts() -> List[Dict[str, Any]]:
    """Sample transaction dictionaries (pre-validation)."""
    return [
        {"date": "11/07", "description": "MEIJER STORE #158", "amount": 113.76},
        {"date": "11/08", "description": "SQ *FRIENDS OF THE LIBRAR", "amount": 2.00},
        {"date": "11/10", "description": "AMAZON.COM", "amount": 45.99},
    ]


@pytest.fixture
def sample_chunk() -> str:
    """Sample PDF text chunk for testing."""
    return """
11/07 MEIJER STORE #158 GRAND RAPIDS MI 113.76
11/08 SQ *FRIENDS OF THE LIBRAR Grand Rapids MI 2.00
11/10 AMAZON.COM AMZN.COM/BILL WA 45.99
TOTAL PURCHASES AND ADJUSTMENTS 161.75
"""


@pytest.fixture
def test_settings() -> Settings:
    """Test settings with default values."""
    reset_settings()
    return Settings(
        todo_folder="test_todo",
        done_folder="test_done",
        llm_model="gemma4",
        llm_temperature=0.1,
        llm_top_p=0.2,
        log_level="DEBUG",
        move_to_done=False
    )


@pytest.fixture(autouse=True)
def cleanup_settings():
    """Reset settings singleton after each test."""
    yield
    reset_settings()


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test_budget.db")
    init_db(path)
    return path
