import re
import unicodedata
from datetime import datetime, timezone
from typing import List, Optional

from models.raw_incident import RawIncident
from models.incident_record import IncidentRecord
from utils.hashing import content_hash
from utils.logger import get_logger

log = get_logger("normaliser")

AFFECTED_SERVICES_CONTEXT_WORDS = {
    "service", "system", "database", "api", "server",
    "cluster", "queue", "cache", "platform", "infrastructure",
}
ROOT_CAUSE_KEYWORDS = [
    "caused by", "due to", "root cause", "because",
    "resulted in", "triggered by",
]
REMEDIATION_KEYWORDS = [
    "fixed by", "resolved by", "mitigated by", "rolled back",
    "restarted", "deployed", "patched",
]
SEVERITY_KEYWORDS = [
    "outage", "degraded", "partial", "complete", "major",
    "minor", "unavailable", "down",
]
DURATION_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*(hours?|minutes?|mins?|hrs?|days?)",
    re.IGNORECASE,
)
DANLUU_REPO_URL = "https://github.com/danluu/post-mortems"


def _clean_description(text: str) -> str:
    if not text:
        return text
    text = re.sub(r"[*_`~]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return unicodedata.normalize("NFC", text)


def _extract_affected_services(description: str) -> List[str]:
    if not description:
        return []
    services = []
    sentences = re.split(r"[.!?]", description)
    for sentence in sentences:
        words = sentence.split()
        for i, word in enumerate(words):
            if word.lower() in AFFECTED_SERVICES_CONTEXT_WORDS:
                window = range(max(0, i - 3), min(len(words), i + 3))
                for j in window:
                    candidate = words[j]
                    if (
                        candidate
                        and candidate[0].isupper()
                        and len(candidate) > 2
                        and candidate.lower() not in AFFECTED_SERVICES_CONTEXT_WORDS
                    ):
                        services.append(candidate)
    return list(dict.fromkeys(services))


def _extract_sentences_with_keywords(text: str, keywords: List[str]) -> List[str]:
    if not text:
        return []
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return [
        s.strip()
        for s in sentences
        if any(kw in s.lower() for kw in keywords)
    ]


def _extract_duration_minutes(description: str) -> Optional[int]:
    if not description:
        return None
    match = DURATION_PATTERN.search(description)
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2).lower()
    if unit.startswith("day"):
        return int(value * 24 * 60)
    if unit.startswith("hour") or unit.startswith("hr"):
        return int(value * 60)
    return int(value)


def _extract_severity(description: str) -> Optional[str]:
    if not description:
        return None
    desc_lower = description.lower()
    found = [kw for kw in SEVERITY_KEYWORDS if kw in desc_lower]
    return ", ".join(found) if found else None


def normalise(raw: RawIncident, source_sha: str, config: dict) -> IncidentRecord:
    """Transform a RawIncident into a canonical IncidentRecord.

    This is the contract-defining step. The resulting IncidentRecord is
    validated by Pydantic before being returned. Validation errors propagate
    to the caller, which logs them and continues with the next record.

    Args:
        raw: A RawIncident from the markdown parser.
        source_sha: The GitHub file SHA from the CrawlResult.
        config: Full application config dict.

    Returns:
        A validated IncidentRecord.

    Raises:
        pydantic.ValidationError: if the record fails schema validation.
    """
    desc_clean = _clean_description(raw.description_raw)

    # Stable ID: hash of primary_url if present, else hash of raw text
    id_input = raw.primary_url or raw.raw_text or ""
    record_id = content_hash(id_input)

    # Source URL: use primary_url or fall back to repo with line anchor
    if raw.primary_url:
        source_url = raw.primary_url
    else:
        line = raw.line_number or ""
        source_url = f"{DANLUU_REPO_URL}#L{line}" if line else DANLUU_REPO_URL

    # Title
    if raw.company_or_service:
        title = raw.company_or_service[:100]
    elif desc_clean:
        first_sentence = re.split(r"[.!?]", desc_clean)[0]
        title = first_sentence[:100].strip() or None
    else:
        title = None

    # Normalised section name
    section_normalised = None
    if raw.section:
        section_normalised = re.sub(r"\W+", "_", raw.section.lower()).strip("_")

    # Date as ISO 8601 date string
    date_str = None
    if raw.date_parsed:
        try:
            date_str = raw.date_parsed.date().isoformat()
        except Exception:
            pass

    # Content hash for deduplication
    hash_input = f"{title or ''}{desc_clean or ''}{source_url or ''}"
    c_hash = content_hash(hash_input)

    tags = [section_normalised] if section_normalised else []

    return IncidentRecord(
        id=record_id,
        source_url=source_url,
        source_type="POSTMORTEM",
        source_sha=source_sha,
        title=title,
        description=desc_clean,
        company=raw.company_or_service,
        section=section_normalised,
        date=date_str,
        affected_services=_extract_affected_services(desc_clean or ""),
        root_causes_raw=_extract_sentences_with_keywords(
            desc_clean or "", ROOT_CAUSE_KEYWORDS
        ),
        remediation_actions_raw=_extract_sentences_with_keywords(
            desc_clean or "", REMEDIATION_KEYWORDS
        ),
        duration_minutes=_extract_duration_minutes(desc_clean or ""),
        severity_raw=_extract_severity(desc_clean or ""),
        tags=tags,
        quality_score=None,
        parse_confidence=raw.parse_confidence,
        low_quality=False,
        content_hash=c_hash,
        potential_duplicate_of=None,
        duplicate_confidence=None,
        ingested_at=datetime.now(tz=timezone.utc).isoformat(),
    )
