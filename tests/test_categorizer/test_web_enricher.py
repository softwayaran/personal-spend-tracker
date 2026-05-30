"""Tests for WebEnricher with mocked search and LLM calls."""

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


def _mock_ddgs(snippets: list[str]) -> MagicMock:
    """Create a mock DDGS instance returning the given snippets."""
    mock_instance = MagicMock()
    mock_instance.text.return_value = [{"body": s} for s in snippets]
    mock_cls = MagicMock(return_value=mock_instance)
    return mock_cls


class TestWebEnricher:
    @patch("budget_parser.categorizer.web_enricher.DDGS")
    @patch("budget_parser.categorizer.web_enricher.ollama.chat")
    def test_enriches_uncategorized_transaction(self, mock_ollama, mock_ddgs, enricher):
        mock_ddgs_instance = MagicMock()
        mock_ddgs_instance.text.return_value = [
            {"body": "Thai Fusion is a Thai restaurant in Grand Rapids"}
        ]
        mock_ddgs.return_value = mock_ddgs_instance
        mock_ollama.return_value = {
            "message": {"content": "Thai restaurant"}
        }

        transactions = [
            {"id": 1, "description": "TST* THAI FUSION GRAND RAPIDS MI", "category": ""}
        ]
        result = enricher.enrich(transactions)

        assert result[0]["context"] == "Thai restaurant"

    @patch("budget_parser.categorizer.web_enricher.DDGS")
    @patch("budget_parser.categorizer.web_enricher.ollama.chat")
    def test_uses_cache_on_second_call(self, mock_ollama, mock_ddgs, enricher):
        mock_ddgs_instance = MagicMock()
        mock_ddgs_instance.text.return_value = [{"body": "Amazon online store"}]
        mock_ddgs.return_value = mock_ddgs_instance
        mock_ollama.return_value = {"message": {"content": "online retail store"}}

        transactions = [{"id": 1, "description": "AMZN MKTP US*ABC123", "category": ""}]
        enricher.enrich(transactions)

        mock_ddgs.reset_mock()
        mock_ollama.reset_mock()

        result = enricher.enrich(transactions)
        assert result[0]["context"] == "online retail store"
        mock_ddgs.assert_not_called()
        mock_ollama.assert_not_called()

    def test_skips_already_categorized(self, enricher):
        transactions = [
            {"id": 1, "description": "NETFLIX", "category": "Utilities"}
        ]
        result = enricher.enrich(transactions)
        assert "context" not in result[0]

    @patch("budget_parser.categorizer.web_enricher.DDGS")
    def test_handles_search_failure_gracefully(self, mock_ddgs, enricher):
        mock_ddgs.return_value.text.side_effect = Exception("Network error")

        transactions = [{"id": 1, "description": "UNKNOWN MERCHANT", "category": ""}]
        result = enricher.enrich(transactions)

        assert result[0].get("context", "") == ""

    @patch("budget_parser.categorizer.web_enricher.DDGS")
    def test_caches_no_result(self, mock_ddgs, enricher, db_path):
        mock_ddgs_instance = MagicMock()
        mock_ddgs_instance.text.return_value = []
        mock_ddgs.return_value = mock_ddgs_instance

        transactions = [{"id": 1, "description": "XYZZY GIBBERISH", "category": ""}]
        enricher.enrich(transactions)

        cached = get_merchant_cache(db_path, "XYZZY GIBBERISH")
        assert cached is not None
        assert cached["business_type"] == "no_result"
