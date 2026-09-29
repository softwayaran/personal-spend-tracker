"""Regex-based merchant name extraction from transaction descriptions."""

import re


_PREFIX_PATTERNS = [
    re.compile(r"^TST\*\s*", re.IGNORECASE),
    re.compile(r"^SQ\s*\*\s*", re.IGNORECASE),
    re.compile(r"^PP\*\s*", re.IGNORECASE),
    re.compile(r"^PAYPAL\s*\*\s*", re.IGNORECASE),
    re.compile(r"^Ant\*", re.IGNORECASE),
]

_STORE_NUMBER = re.compile(r"\s*#\d+\b")
_PHONE_NUMBER = re.compile(r"\d{3}[-.]?\d{3,}[-.]?\d{0,4}\w{0,2}")
_ZIP_CODE = re.compile(r"\b\d{5}(-\d{4})?\s*$")

_STATE_ABBREV = re.compile(
    r"\b(AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|"
    r"MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|"
    r"VA|WA|WV|WI|WY)\s*$"
)

_TRAILING_DOTCOM = re.compile(r"\.COM\b", re.IGNORECASE)

_KNOWN_CITIES = re.compile(
    r"\b(SPRINGFIELD|GRAND RAPIDS|DETROIT|CHICAGO|NEW YORK|LOS ANGELES|"
    r"SAN FRANCISCO|HOUSTON|DALLAS|AUSTIN|SEATTLE|PORTLAND|DENVER|PHOENIX|"
    r"COLUMBUS|INDIANAPOLIS|MINNEAPOLIS|NASHVILLE|ORLANDO|TAMPA|ATLANTA|"
    r"CHARLOTTE|RALEIGH|PITTSBURGH|CLEVELAND|CINCINNATI|MILWAUKEE|KANSAS CITY|"
    r"ST LOUIS|SALT LAKE CITY|LAS VEGAS|SAN DIEGO|SAN JOSE|SACRAMENTO|"
    r"JACKSONVILLE|MEMPHIS|LOUISVILLE|RICHMOND|BUFFALO|ROCHESTER|BIRMINGHAM)\b",
    re.IGNORECASE,
)


class MerchantExtractor:
    """Extracts clean merchant names from raw transaction descriptions using regex."""

    def extract(self, description: str) -> str:
        """Clean a transaction description into a merchant name.

        Args:
            description: Raw transaction description from bank statement

        Returns:
            Cleaned, title-cased merchant name. Empty string if input is blank.
        """
        text = description.strip()
        if not text:
            return ""

        for pattern in _PREFIX_PATTERNS:
            text = pattern.sub("", text)

        text = _STORE_NUMBER.sub("", text)
        text = _PHONE_NUMBER.sub("", text)
        text = _TRAILING_DOTCOM.sub("", text)
        text = _KNOWN_CITIES.sub("", text)
        text = _ZIP_CODE.sub("", text)
        text = _STATE_ABBREV.sub("", text)

        text = re.sub(r"[*#]+", " ", text)
        text = re.sub(r"\s+", " ", text).strip()

        if not text:
            return ""

        return text.title()
