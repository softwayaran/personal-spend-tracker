"""Text processing utilities."""

import re
from typing import Any, Union, List, Dict


def strip_markdown_fences(text: str) -> str:
    """Strip markdown code fences (```json ... ```) from LLM output.

    Args:
        text: Raw LLM output string (already stripped)

    Returns:
        Text with code fences removed
    """
    if text.startswith("```"):
        text = re.sub(r'```(?:json)?\n?', '', text).strip()
    return text


def parse_amount(amount_str: Union[str, int, float]) -> float:
    """
    Safely parse amount string to float.

    Handles various formats:
    - $1,234.56
    - -$1234.56
    - 1234.56
    - 1,234

    Args:
        amount_str: Amount as string, int, or float

    Returns:
        Parsed amount as float (0.0 if parsing fails)
    """
    if isinstance(amount_str, (int, float)):
        return float(amount_str)

    try:
        # Remove $ and commas, then convert
        cleaned = str(amount_str).replace('$', '').replace(',', '').strip()
        return float(cleaned)
    except (ValueError, TypeError):
        return 0.0


def normalize_ai_output(data: Any) -> List[Dict[str, Any]]:
    """
    Normalize AI output to consistent list format.

    Fixes the 'Dictionary Bug' where AI might return:
    - {'transactions': [...]} instead of [...]
    - {'data': [...]} instead of [...]
    - or other wrapped formats

    Args:
        data: AI output (list or dict)

    Returns:
        List of transactions
    """
    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        # Look for any key that contains a list
        for key, value in data.items():
            if isinstance(value, list):
                return value
        # Single transaction object (has "index" key) — wrap in list
        if "index" in data:
            return [data]

    return []
