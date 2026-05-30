"""LLM-based transaction categorization agent."""

import json
from typing import List, Dict, Any

import ollama

from budget_parser.utils.logger import get_logger
from budget_parser.utils.text_utils import normalize_ai_output, strip_markdown_fences

logger = get_logger(__name__)


class CategorizationAgent:
    """Categorizes transactions into preset categories using Ollama LLM."""

    def __init__(
        self,
        model: str,
        categories: List[Dict[str, str]],
        temperature: float = 0.1,
        top_p: float = 0.2,
        num_predict: int = 2000,
        batch_size: int = 20,
    ):
        """
        Initialize the categorization agent.

        Args:
            model: Ollama model name
            categories: List of dicts with 'category' and 'sub_category' keys
            temperature: LLM temperature (lower = more deterministic)
            top_p: LLM top_p parameter
            num_predict: Max tokens to generate
            batch_size: Number of transactions to send per LLM call
        """
        self.model = model
        self.categories = categories
        self.temperature = temperature
        self.top_p = top_p
        self.num_predict = num_predict
        self.batch_size = batch_size
        self._categories_text = self._format_categories()

    def _format_categories(self) -> str:
        """Format categories list as numbered text for the prompt."""
        lines = []
        for i, pair in enumerate(self.categories, 1):
            lines.append(f"{i}. Category: {pair['category']} | Sub Category: {pair['sub_category']}")
        return "\n".join(lines)

    def _build_prompt(self, transactions: List[Dict[str, Any]]) -> str:
        """Build the categorization prompt for a batch of transactions."""
        tx_lines_list = []
        for item in transactions:
            line = f'{item["index"]}: {item["description"]}'
            if item.get("context"):
                line += f' (Context: {item["context"]})'
            tx_lines_list.append(line)
        tx_lines = "\n".join(tx_lines_list)

        return f"""You are a personal finance categorization assistant. Categorize each transaction using ONLY the predefined category/sub-category pairs listed below.

VALID CATEGORY/SUB-CATEGORY PAIRS:
{self._categories_text}

INSTRUCTIONS:
1. For each transaction, pick the BEST matching category and sub-category from the list above.
2. Also extract a clean, short merchant name (e.g., "Netflix", "Meijer", "Starbucks").
3. If the transaction does NOT clearly fit any category, use "" (empty string) for category and sub_category.
4. Return a JSON array with one object per transaction, in the same order as input.
5. Each object must have exactly these keys: "index" (integer), "category" (string), "sub_category" (string), "merchant" (string).
6. Return ONLY valid JSON array, no markdown, no explanations.

Use these hints for categorization:
1. If the description has the words "Restaurant", "Cafe", "Bar", or "Food", it is "Restaurants" category. 
2. If it has "Grocery", "Supermarket", or "Market", it is "Grocery" category.
3. If it has Gas station names or words like "Fuel", "Gas", "C Store", it is "Car" category and "Gas" sub-category.

EXAMPLES:
- "Netflix.com408-5403700CA" → {{"index":0, "category":"Utilities", "sub_category":"Streaming", "merchant":"Netflix"}}
- "MEIJER STORE #158 GRAND RAPIDS MI" → {{"index":1, "category":"Grocery", "sub_category":"Grocery", "merchant":"Meijer"}}
- "NATIONAL MALL PARKING WASHINGTON DC" → {{"index":2, "category":"", "sub_category":"", "merchant":"National Mall Parking"}}
- "AMAZONMKTPL" → {{"index":3, "category":"Online Shopping", "sub_category":"Amazon", "merchant":"Amazon"}}
- "Ant*MoboreaderHongKongChinaHK" → {{"index":4, "category":"Hobby", "sub_category":"Books", "merchant":"Moboreader"}}
- "JAKU SUSHI & GRILL GRAND RAPIDS" → {{"index":5, "category":"Restaurants", "sub_category":"Family", "merchant":"Jaku Sushi & Grill"}}

TRANSACTIONS TO CATEGORIZE:
{tx_lines}

JSON OUTPUT:"""

    def _call_llm(self, transactions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Send a batch of transactions to Ollama and return categorization results.

        Tries a batch call first. If the LLM returns fewer results than
        expected, falls back to one-at-a-time calls for the missing items.
        """
        results = self._call_llm_batch(transactions)

        returned_indices = {int(r.get("index", -1)) for r in results}
        missing = [tx for tx in transactions if tx["index"] not in returned_indices]

        if missing:
            logger.debug(
                f"Batch returned {len(results)}/{len(transactions)}, "
                f"retrying {len(missing)} individually"
            )
            for tx in missing:
                single = self._call_llm_batch([tx])
                for item in single:
                    item["index"] = tx["index"]
                results.extend(single)

        return results

    def _call_llm_batch(self, transactions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Send transactions to Ollama and parse the JSON response."""
        prompt = self._build_prompt(transactions)

        try:
            response = ollama.chat(
                model=self.model,
                format="json",
                options={
                    "temperature": self.temperature,
                    "top_p": self.top_p,
                    "num_predict": self.num_predict,
                },
                messages=[
                    {
                        "role": "system",
                        "content": "You are a financial transaction categorization assistant. Always return valid JSON."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            )

            content = response['message']['content'].strip()
            content = strip_markdown_fences(content)

            data = json.loads(content)
            data = normalize_ai_output(data)

            return data

        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error from LLM: {e}")
            return []
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return []

    def categorize(self, transactions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Categorize a list of transactions.

        Skips rows that already have a category (for rerun support).
        Returns the full list with category, sub_category, and merchant fields populated.

        Args:
            transactions: List of dicts with at least 'description', optionally 'category'

        Returns:
            Same list with 'category', 'sub_category', 'merchant' filled in where possible
        """
        results = [dict(tx) for tx in transactions]

        # Identify rows that still need categorization
        pending = [
            (i, tx)
            for i, tx in enumerate(results)
            if not tx.get('category', '').strip()
        ]

        if not pending:
            logger.info("All transactions already categorized, nothing to do.")
            return results

        logger.info(
            f"Categorizing {len(pending)} transactions "
            f"({len(transactions) - len(pending)} already done) "
            f"in batches of {self.batch_size}..."
        )

        for batch_start in range(0, len(pending), self.batch_size):
            batch = pending[batch_start: batch_start + self.batch_size]
            orig_indices = [i for i, _ in batch]
            batch_txs = [tx for _, tx in batch]

            # Build indexed list for the LLM (local 0-based index within batch)
            indexed = [
                {"index": j, "description": tx["description"], "context": tx.get("context", "")}
                for j, tx in enumerate(batch_txs)
            ]

            llm_results = self._call_llm(indexed)

            applied = 0
            for item in llm_results:
                try:
                    local_idx = int(item.get("index", -1))
                    if 0 <= local_idx < len(orig_indices):
                        orig_idx = orig_indices[local_idx]
                        results[orig_idx]["category"] = str(item.get("category", "")).strip()
                        results[orig_idx]["sub_category"] = str(item.get("sub_category", "")).strip()
                        results[orig_idx]["merchant"] = str(item.get("merchant", "")).strip()
                        if results[orig_idx]["category"]:
                            applied += 1
                except (ValueError, KeyError, TypeError) as e:
                    logger.warning(f"Could not apply LLM result {item}: {e}")

            batch_num = batch_start // self.batch_size + 1
            total_batches = (len(pending) + self.batch_size - 1) // self.batch_size
            logger.info(f"Batch {batch_num}/{total_batches}: {applied}/{len(batch)} categorized")

        categorized = sum(1 for tx in results if tx.get("category", "").strip())
        logger.info(f"Done: {categorized}/{len(results)} transactions categorized")
        return results
