from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class RawIncident:
    """Represents a parsed incident entry before normalisation.

    All fields are nullable — the parser may not be able to extract
    everything from every entry. This model has no validation by design;
    it represents raw extracted data in its most faithful form.
    """

    # The original unmodified bullet point text, preserved exactly as found
    raw_text: Optional[str] = None

    # The most recent ## heading seen before this entry
    section: Optional[str] = None

    # Extracted from the first link text in the entry
    company_or_service: Optional[str] = None

    # The first URL found in the entry
    primary_url: Optional[str] = None

    # Any additional URLs found in the entry
    secondary_urls: List[str] = field(default_factory=list)

    # Entry text with markdown link syntax removed but otherwise unmodified
    description_raw: Optional[str] = None

    # The raw date string as found in the text, before any parsing
    date_raw: Optional[str] = None

    # A Python datetime if date extraction succeeded, else None
    date_parsed: Optional[datetime] = None

    # Float 0–1 indicating parser confidence in extracted fields
    parse_confidence: float = 0.0

    # Line number in the source file where this entry started
    line_number: Optional[int] = None

    # Content fetched from the primary URL (only populated when link following is enabled)
    external_content: Optional[str] = None
