"""Integration test for the full web enrichment → categorization flow."""

import os
import tempfile
from unittest.mock import patch, MagicMock

import pytest

from budget_parser.categorizer.web_enricher import WebEnricher
from budget_parser.categorizer.agent import CategorizationAgent
from budget_parser.database.db import init_db, get_merchant_cache


@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    yield path
    os.unlink(path)


@patch("budget_parser.categorizer.web_enricher.httpx.get")
@patch("budget_parser.categorizer.web_enricher.ollama.chat")
def test_enrichment_feeds_into_categorization_prompt(mock_ollama_enrich, mock_httpx, db_path):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = '<div class="result__snippet">Thai Fusion is a Thai restaurant</div>'
    mock_httpx.return_value = mock_resp
    mock_ollama_enrich.return_value = {"message": {"content": "Thai restaurant"}}

    enricher = WebEnricher(db_path=db_path, delay=0.0)
    transactions = [
        {"id": 1, "description": "TST* THAI FUSION GRAND RAPIDS MI", "category": ""},
    ]
    enriched = enricher.enrich(transactions)

    assert enriched[0]["context"] == "Thai restaurant"

    agent = CategorizationAgent(
        model="llama3",
        categories=[{"category": "Restaurants", "sub_category": "Family"}],
    )
    indexed = [{"index": 0, "description": enriched[0]["description"], "context": enriched[0].get("context", "")}]
    prompt = agent._build_prompt(indexed)

    assert "(Context: Thai restaurant)" in prompt
    assert "TST* THAI FUSION GRAND RAPIDS MI" in prompt


@patch("budget_parser.categorizer.web_enricher.httpx.get")
@patch("budget_parser.categorizer.web_enricher.ollama.chat")
def test_cached_result_skips_network(mock_ollama, mock_httpx, db_path):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = '<div class="result__snippet">Starbucks coffee chain</div>'
    mock_httpx.return_value = mock_resp
    mock_ollama.return_value = {"message": {"content": "Coffee chain"}}

    enricher = WebEnricher(db_path=db_path, delay=0.0)
    transactions = [{"id": 1, "description": "STARBUCKS #12345", "category": ""}]

    enricher.enrich(transactions)
    assert mock_httpx.call_count == 1

    mock_httpx.reset_mock()
    mock_ollama.reset_mock()

    result = enricher.enrich(transactions)
    assert result[0]["context"] == "Coffee chain"
    mock_httpx.assert_not_called()
