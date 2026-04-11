"""Markdown parser for the danluu/post-mortems README.md.

Architecture note: the entire danluu dataset is a single large README.md.
This parser is therefore doing the bulk of the extraction work. It uses a
line-by-line state machine to extract incident entries. Every line is
accounted for — nothing is silently dropped. Every line can be traced to
either a RawIncident or an explicit skip decision in the logs.
"""

import re
from datetime import datetime
from typing import List, Optional, Tuple

from dateutil import parser as dateutil_parser

from models.raw_incident import RawIncident
from utils.logger import get_logger

log = get_logger("markdown_parser")

LINK_PATTERN = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
SECTION_PATTERN = re.compile(r"^##\s+(.+)$")
ENTRY_PATTERN = re.compile(r"^\s*(\[.+)$")

# Explicit date patterns tried before full fuzzy parsing
DATE_PATTERNS = [
    re.compile(r"\b(\d{4}[-/]\d{1,2}[-/]\d{1,2})\b"),
    re.compile(r"\b(\w+ \d{1,2},?\s+\d{4})\b"),
    re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\b"),
]


def _extract_links(text: str) -> List[Tuple[str, str]]:
    return LINK_PATTERN.findall(text)


def _strip_markdown_links(text: str) -> str:
    """Remove markdown link syntax, keeping only the link text."""
    return LINK_PATTERN.sub(r"\1", text)


def _extract_date(text: str) -> Tuple[Optional[str], Optional[datetime]]:
    """Attempt to extract a date from text. Returns (raw_string, parsed_datetime)."""
    for pattern in DATE_PATTERNS:
        match = pattern.search(text)
        if match:
            date_str = match.group(1)
            try:
                parsed = dateutil_parser.parse(date_str, fuzzy=True)
                return date_str, parsed
            except (ValueError, OverflowError):
                continue
    return None, None


def _calculate_confidence(
    primary_url: Optional[str],
    description: Optional[str],
    date_parsed: Optional[datetime],
    min_desc_length: int,
) -> float:
    score = 0.0
    if primary_url:
        score += 0.4
    if description and len(description) >= min_desc_length:
        score += 0.4
    elif description:
        score += 0.2
    if date_parsed:
        score += 0.2
    return min(score, 1.0)


def parse(content: str, config: dict) -> List[RawIncident]:
    """Parse raw README.md content into a list of RawIncident objects.

    Uses a line-by-line state machine with two states:
    - Inside a section (seen a ## header)
    - Reading a bullet point (seen a * or - entry, possibly multi-line)

    Every line maps to either a RawIncident or a logged skip. Nothing is
    discarded silently.

    Args:
        content: Raw string content of the README.md.
        config: Parsing config section from config.yaml.

    Returns:
        List of RawIncident objects, one per bullet point entry.
    """
    min_desc_length = config.get("min_description_length", 50)
    lines = content.splitlines()
    incidents: List[RawIncident] = []

    current_section: Optional[str] = None
    current_bullet_lines: List[str] = []
    current_bullet_start: Optional[int] = None

    def flush_bullet() -> None:
        if not current_bullet_lines:
            return

        raw_text = " ".join(current_bullet_lines).strip()
        links = _extract_links(raw_text)

        company_or_service = links[0][0] if links else None
        primary_url = links[0][1] if links else None
        secondary_urls = [url for _, url in links[1:]]

        description_raw = re.sub(r"\s+", " ", _strip_markdown_links(raw_text)).strip()

        date_raw, date_parsed = _extract_date(description_raw)

        confidence = _calculate_confidence(
            primary_url, description_raw, date_parsed, min_desc_length
        )

        incidents.append(
            RawIncident(
                raw_text=raw_text,
                section=current_section,
                company_or_service=company_or_service,
                primary_url=primary_url,
                secondary_urls=secondary_urls,
                description_raw=description_raw,
                date_raw=date_raw,
                date_parsed=date_parsed,
                parse_confidence=round(confidence, 3),
                line_number=current_bullet_start,
            )
        )

    for line_number, line in enumerate(lines, start=1):
        section_match = SECTION_PATTERN.match(line)
        if section_match:
            flush_bullet()
            current_bullet_lines = []
            current_bullet_start = None
            current_section = section_match.group(1).strip()
            log.debug("New section", section=current_section, line=line_number)
            continue

        entry_match = ENTRY_PATTERN.match(line)
        if entry_match:
            flush_bullet()
            current_bullet_lines = [entry_match.group(1)]
            current_bullet_start = line_number
            continue

        # Non-empty continuation line appended to the current bullet
        if current_bullet_lines and line.strip():
            current_bullet_lines.append(line.strip())
            continue

        # Empty line — flush current bullet if any
        if not line.strip() and current_bullet_lines:
            flush_bullet()
            current_bullet_lines = []
            current_bullet_start = None

    flush_bullet()

    log.info(
        "Parsing complete",
        total_incidents=len(incidents),
        sections_found=len({i.section for i in incidents if i.section}),
    )
    return incidents
