"""Pure functions for cleaning transaction descriptions into search queries and cache keys."""

import re


_PREFIX_PATTERNS = [
    re.compile(r"^TST\*\s*", re.IGNORECASE),
    re.compile(r"^SQ\s*\*\s*", re.IGNORECASE),
    re.compile(r"^PP\*\s*", re.IGNORECASE),
    re.compile(r"^Ant\*", re.IGNORECASE),
]

_TRAILING_CODE_PATTERN = re.compile(r"\*\w{5,}$")

_PHONE_OR_ID_PATTERN = re.compile(r"\d{3}[-.]?\d{3,}[-.]?\d{0,4}\w{0,2}$")

_STORE_NUMBER_PATTERN = re.compile(r"#\d+", re.IGNORECASE)

_STATE_ZIP_PATTERN = re.compile(
    r"\b[A-Z]{2}\s*\d{5}(-\d{4})?\s*$"
)

_TRAILING_STATE_PATTERN = re.compile(
    r"\b(AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY)\s*$"
)

_TRAILING_COUNTRY_CODE = re.compile(
    r"(?<!\s)(US|CA|UK|GB|AU|HK|CN|IN|JP|DE|FR|IT|ES|NL|BR|MX)\s*$", re.IGNORECASE
)

_COUNTRY_CITY_SUFFIX = re.compile(
    r"(Hong\s*Kong|China|United\s*States|Canada|Australia)\w*\s*$", re.IGNORECASE
)


def normalize_description(description: str) -> str:
    """Normalize a transaction description into a clean search query / cache key.

    Strips merchant prefixes, trailing transaction codes, store numbers,
    state abbreviations, zip codes, and country codes.
    """
    text = description.strip()
    if not text:
        return ""

    for pattern in _PREFIX_PATTERNS:
        text = pattern.sub("", text)

    text = _PHONE_OR_ID_PATTERN.sub("", text)
    text = _TRAILING_CODE_PATTERN.sub("", text)
    text = _STORE_NUMBER_PATTERN.sub("", text)
    text = _STATE_ZIP_PATTERN.sub("", text)
    text = _TRAILING_STATE_PATTERN.sub("", text)
    text = _TRAILING_COUNTRY_CODE.sub("", text)
    text = _COUNTRY_CITY_SUFFIX.sub("", text)

    text = re.sub(r"\s+", " ", text).strip()

    return text
