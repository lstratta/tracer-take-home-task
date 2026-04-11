from typing import List, Optional
from pydantic import BaseModel, model_validator


class IncidentRecord(BaseModel):
    """Canonical normalised incident record schema.

    This is the contract model between the ingestion system and downstream
    classifier and scenario generation systems. All fields are explicitly typed.
    Optional fields default to None; list fields default to empty lists.
    """

    # Unique stable identifier — SHA-256 hash of primary_url or raw_text
    id: str

    # URL of the original incident report
    source_url: Optional[str] = None

    # Always "POSTMORTEM" for records from this ingestion source
    source_type: str = "POSTMORTEM"

    # SHA of the danluu README.md at crawl time — traces record to exact source version
    source_sha: Optional[str] = None

    # Company or service name extracted from the first markdown link text
    title: Optional[str] = None

    # Cleaned description text with markdown formatting removed and unicode normalised
    description: Optional[str] = None

    # The company_or_service field from the raw incident
    company: Optional[str] = None

    # Section heading normalised to lowercase with underscores
    section: Optional[str] = None

    # Incident date as ISO 8601 string; null if not found — never guessed
    date: Optional[str] = None

    # Service names extracted from description via heuristics
    affected_services: List[str] = []

    # Sentences containing root cause signal keywords
    root_causes_raw: List[str] = []

    # Sentences containing remediation signal keywords
    remediation_actions_raw: List[str] = []

    # Duration converted to minutes; null if not found in description
    duration_minutes: Optional[int] = None

    # Severity indicator words found in description (e.g. "outage", "degraded")
    severity_raw: Optional[str] = None

    # Initially populated from section; may be extended by later pipeline stages
    tags: List[str] = []

    # Quality score 0–1 assigned by quality_scorer; null until scored
    quality_score: Optional[float] = None

    # Carried over from RawIncident
    parse_confidence: float = 0.0

    # True if quality_score is below the configured minimum threshold
    low_quality: bool = False

    # Hash of normalised title + description + source_url; used for deduplication
    content_hash: str

    # ID of a potential duplicate record detected by SimHash comparison
    potential_duplicate_of: Optional[str] = None

    # Similarity score for the potential duplicate (0–1)
    duplicate_confidence: Optional[float] = None

    # ISO 8601 timestamp of when this record was created by the normaliser
    ingested_at: str

    @model_validator(mode="after")
    def title_or_description_required(self) -> "IncidentRecord":
        """Reject records where both title and description are null or empty."""
        if not self.title and not self.description:
            raise ValueError(
                "At least one of 'title' or 'description' must be non-empty"
            )
        return self
