import hashlib
import re
import unicodedata

from simhash import Simhash


def content_hash(text: str) -> str:
    """Return a truncated SHA-256 hex digest (first 8 characters) of the input text.

    Normalises whitespace and lowercases before hashing to ensure the same
    incident always gets the same ID across runs.

    Pure function — same input always produces same output.
    """
    normalised = re.sub(r"\s+", " ", text.lower().strip())
    normalised = unicodedata.normalize("NFC", normalised)
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:8]


def compute_simhash(text: str) -> int:
    """Return a 64-bit SimHash integer of the input text.

    Tokenises input into words before hashing. Used for near-duplicate detection
    via Hamming distance comparison.

    Pure function — same input always produces same output.
    """
    tokens = re.findall(r"\w+", text.lower())
    return Simhash(tokens).value
