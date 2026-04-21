"""Web-based transaction description enrichment using DuckDuckGo search."""

import time
from typing import Dict, List, Optional

import httpx
import ollama
from bs4 import BeautifulSoup

from budget_parser.categorizer.description_normalizer import normalize_description
from budget_parser.database.db import get_merchant_cache, upsert_merchant_cache
from budget_parser.utils.logger import get_logger

logger = get_logger(__name__)

_SEARCH_URL = "https://html.duckduckgo.com/html/"
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


class WebEnricher:
    """Enriches transaction descriptions with business context from web search."""

    def __init__(
        self,
        db_path: str,
        delay: float = 1.5,
        max_snippets: int = 3,
        model: str = "llama3",
    ):
        self.db_path = db_path
        self.delay = delay
        self.max_snippets = max_snippets
        self.model = model

    def enrich(self, transactions: List[Dict]) -> List[Dict]:
        """Enrich uncategorized transactions with web-searched business context.

        Adds a 'context' field to each transaction that was enriched.
        Already-categorized transactions are skipped.
        """
        results = [dict(tx) for tx in transactions]

        for tx in results:
            if tx.get("category", "").strip():
                continue

            description = tx.get("description", "")
            normalized = normalize_description(description)
            if not normalized:
                continue

            context = self._get_context(normalized)
            if context and context != "no_result":
                tx["context"] = context

        return results

    def _get_context(self, normalized_description: str) -> Optional[str]:
        """Get business context: from cache or via web search + LLM summary."""
        cached = get_merchant_cache(self.db_path, normalized_description)
        if cached:
            return cached["business_type"]

        snippets = self._search(normalized_description)
        if not snippets:
            upsert_merchant_cache(self.db_path, normalized_description, "", "no_result")
            return "no_result"

        summary = self._summarize(normalized_description, snippets)
        merchant_name = normalized_description.split()[0] if normalized_description else ""
        upsert_merchant_cache(self.db_path, normalized_description, merchant_name, summary)

        if self.delay > 0:
            time.sleep(self.delay)

        return summary

    def _search(self, query: str) -> List[str]:
        """Search DuckDuckGo and return snippet texts."""
        try:
            response = httpx.get(
                _SEARCH_URL,
                params={"q": f"{query} merchant"},
                headers={"User-Agent": _USER_AGENT},
                timeout=10.0,
            )
            if response.status_code != 200:
                logger.warning(f"Search returned status {response.status_code} for '{query}'")
                return []

            soup = BeautifulSoup(response.text, "html.parser")
            snippet_elements = soup.select(".result__snippet")
            snippets = [el.get_text(strip=True) for el in snippet_elements[: self.max_snippets]]

            if not snippets:
                logger.debug(f"No search snippets found for '{query}'")

            return snippets

        except Exception as e:
            logger.warning(f"Search failed for '{query}': {e}")
            return []

    def _summarize(self, description: str, snippets: List[str]) -> str:
        """Use local LLM to summarize search snippets into a business type."""
        snippets_text = "\n".join(f"- {s}" for s in snippets)
        prompt = (
            f"Based on these search results about '{description}', "
            f"what type of business or service is this? Reply in 5 words or fewer.\n\n"
            f"Search results:\n{snippets_text}"
        )

        try:
            response = ollama.chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                options={"temperature": 0.1, "num_predict": 20},
            )
            return response["message"]["content"].strip()
        except Exception as e:
            logger.warning(f"Summarization failed for '{description}': {e}")
            return snippets[0][:50] if snippets else ""
