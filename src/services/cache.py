import hashlib

PARSER_VERSION = "2.0"
MATCH_VERSION = "3.0"


def calculate_sha256(text: str) -> str:
    """Calculates the SHA-256 hash of the given string."""
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
