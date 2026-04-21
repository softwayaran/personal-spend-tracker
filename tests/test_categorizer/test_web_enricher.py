"""Tests for WebEnricher with mocked HTTP and LLM calls."""

import os
import tempfile
from unittest.mock import patch, MagicMock

import pytest

from budget_parser.categorizer.web_enricher import WebEnricher
from budget_parser.database.db import init_db, get_merchant_cache


@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    yield path
    os.unlink(path)


@pytest.fixture
def enricher(db_path):
    return WebEnricher(db_path=db_path, delay=0.0, max_snippets=2, model="llama3")


def _mock_search_response(snippet_text: str) -> MagicMock:
    """Create a mock httpx response with DuckDuckGo-like HTML."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = f'<div class="result__snippet">{snippet_text}</div>'
    return mock_resp


class TestWebEnricher:
    @patch("budget_parser.categorizer.web_enricher.httpx.get")
    @patch("budget_parser.categorizer.web_enricher.ollama.chat")
    def test_enriches_uncategorized_transaction(self, mock_ollama, mock_httpx, enricher):
        mock_httpx.return_value = _mock_search_response(
            "Thai Fusion is a Thai restaurant in Grand Rapids"
        )
        mock_ollama.return_value = {
            "message": {"content": "Thai restaurant"}
        }

        transactions = [
            {"id": 1, "description": "TST* THAI FUSION GRAND RAPIDS MI", "category": ""}
        ]
        result = enricher.enrich(transactions)

        assert result[0]["context"] == "Thai restaurant"

    @patch("budget_parser.categorizer.web_enricher.httpx.get")
    @patch("budget_parser.categorizer.web_enricher.ollama.chat")
    def test_uses_cache_on_second_call(self, mock_ollama, mock_httpx, enricher):
        mock_httpx.return_value = _mock_search_response("Amazon online store")
        mock_ollama.return_value = {"message": {"content": "online retail store"}}

        transactions = [{"id": 1, "description": "AMZN MKTP US*ABC123", "category": ""}]
        enricher.enrich(transactions)

        mock_httpx.reset_mock()
        mock_ollama.reset_mock()

        result = enricher.enrich(transactions)
        assert result[0]["context"] == "online retail store"
        mock_httpx.assert_not_called()
        mock_ollama.assert_not_called()

    def test_skips_already_categorized(self, enricher):
        transactions = [
            {"id": 1, "description": "NETFLIX", "category": "Utilities"}
        ]
        result = enricher.enrich(transactions)
        assert "context" not in result[0]

    @patch("budget_parser.categorizer.web_enricher.httpx.get")
    def test_handles_search_failure_gracefully(self, mock_httpx, enricher):
        mock_httpx.side_effect = Exception("Network error")

        transactions = [{"id": 1, "description": "UNKNOWN MERCHANT", "category": ""}]
        result = enricher.enrich(transactions)

        assert result[0].get("context", "") == ""

    @patch("budget_parser.categorizer.web_enricher.httpx.get")
    def test_caches_no_result(self, mock_httpx, enricher, db_path):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body>No results</body></html>"
        mock_httpx.return_value = mock_resp

        transactions = [{"id": 1, "description": "XYZZY GIBBERISH", "category": ""}]
        enricher.enrich(transactions)

        cached = get_merchant_cache(db_path, "XYZZY GIBBERISH")
        assert cached is not None
        assert cached["business_type"] == "no_result"
