"""LLM-based transaction extraction."""

import json
from typing import List, Dict, Any
import ollama

from budget_parser.utils.logger import get_logger
from budget_parser.utils.text_utils import normalize_ai_output, strip_markdown_fences

logger = get_logger(__name__)


class LLMExtractor:
    """Extracts transactions using LLM (Ollama)."""

    def __init__(
        self,
        model: str = "gemma4",
        temperature: float = 0.1,
        top_p: float = 0.2,
        num_predict: int = 3000
    ):
        """
        Initialize LLM extractor.

        Args:
            model: Ollama model name
            temperature: LLM temperature (0.0-2.0, lower = more deterministic)
            top_p: LLM top_p parameter (0.0-1.0, lower = more focused)
            num_predict: Maximum tokens to generate
        """
        self.model = model
        self.temperature = temperature
        self.top_p = top_p
        self.num_predict = num_predict

    def extract(self, chunk: str) -> List[Dict[str, Any]]:
        """
        Extract transactions from text chunk using LLM.

        Args:
            chunk: Text chunk to process

        Returns:
            List of transaction dictionaries
        """
        prompt = self._build_prompt(chunk)

        logger.debug(f"Sending chunk to LLM (model={self.model})")
        logger.debug(f"Prompt preview: {prompt[:200]}...")

        try:
            response = ollama.chat(
                model=self.model,
                format={
                    "type": "object",
                    "properties": {
                        "transactions": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "date": {"type": "string"},
                                    "description": {"type": "string"},
                                    "amount": {"type": "number"},
                                },
                                "required": ["date", "description", "amount"],
                            },
                        }
                    },
                    "required": ["transactions"],
                },
                options={
                    "temperature": self.temperature,
                    "top_p": self.top_p,
                    "num_predict": self.num_predict,
                },
                messages=[
                    {
                        "role": "system",
                        "content": "You are a transaction extraction tool. Extract only what you see in the text."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            )

            return self._parse_response(response)

        except Exception as e:
            logger.error(f"LLM extraction failed: {str(e)}")
            return []

    def _build_prompt(self, chunk: str) -> str:
        """
        Build extraction prompt for LLM.

        Args:
            chunk: Text chunk to process

        Returns:
            Formatted prompt string
        """
        return f"""Extract financial transactions from the text below. Look for lines that have a DATE at the start, followed by a DESCRIPTION, and ending with an AMOUNT.

Goal: Identify individual transactions and extract their details.

INSTRUCTIONS:
1. Ignore any text that does not pertain to transactions. Focus on lines that contain dates, descriptions and amounts
2. Extract the date, full description (everything between date and amount), and amount
3. Return ONLY valid JSON - no explanations, no markdown, no comments
4. Extract the following details from the provided text chunk:
   4.1. Date of Transaction
   4.2. Description of Transaction
   4.3. Amount
5. Do not assume +/- signs for amounts. Keep the amount as it appears in the text. If it has a minus sign, keep it. If not, keep it as is. Do not infer or change the sign.
6. If there are multiple dates, pick the transaction date. Sometimes referred to as "trans date".
7. Dates may appear as MM/DD, Month DD, or Mon DD (e.g., "01/22", "January 22", "Jan 22"). Normalize all output dates to MM/DD.
8. If no transactions found, return empty array: []

EXAMPLES FROM TYPICAL BANK STATEMENTS:

Input text:
"11/07 MEIJER STORE #158 GRAND RAPIDS MI 113.76
11/08 SQ *FRIENDS OF THE LIBRAR Grand Rapids MI 2.00
12/05 AUTOMATIC PAYMENT - THANK YOU -1,955.00
January 22 NETFLIX.COM 15.99"

Expected output:
[
  {{"date": "11/07", "description": "MEIJER STORE #158 GRAND RAPIDS MI", "amount": 113.76}},
  {{"date": "11/08", "description": "SQ *FRIENDS OF THE LIBRAR Grand Rapids MI", "amount": 2.00}},
  {{"date": "12/05", "description": "AUTOMATIC PAYMENT - THANK YOU", "amount": -1955.00}},
  {{"date": "01/22", "description": "NETFLIX.COM", "amount": 15.99}}
]

WHAT TO EXTRACT:
- Any line starting with a date (MM/DD, Month DD, or Mon DD) followed by text and a number
- Include ALL transactions: purchases, payments, fees, everything

WHAT TO SKIP:
- Headers like "PURCHASE", "PAYMENTS AND OTHER CREDITS", "ACCOUNT ACTIVITY"
- Lines without dates
- Lines without amounts
- Account messages, terms and conditions, contact information

OUTPUT RULES:
- Amounts should be numbers (not strings), but keep the sign as it appears in the text
- Keep descriptions exactly as shown
- Return valid JSON array only

TEXT TO ANALYZE:
\"\"\"
{chunk}
\"\"\"

JSON OUTPUT:"""

    def _parse_response(self, response: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Parse LLM response and extract transaction data.

        Args:
            response: Raw LLM response

        Returns:
            List of transaction dictionaries
        """
        try:
            response_content = response['message']['content'].strip()
            response_content = strip_markdown_fences(response_content)

            logger.debug(f"LLM response preview: {response_content[:200]}...")

            raw_data = json.loads(response_content)
            data = normalize_ai_output(raw_data)

            logger.debug(f"LLM extracted {len(data)} raw transactions")
            return data

        except json.JSONDecodeError as e:
            logger.error(f"JSON decoding error: {str(e)}")
            logger.error(f"Raw response: {response_content[:500] if 'response_content' in locals() else 'N/A'}")
            return []
        except KeyError as e:
            logger.error(f"Unexpected response format: {str(e)}")
            return []
