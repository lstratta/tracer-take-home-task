import re
from urllib.parse import urlparse

from models.incident_record import IncidentRecord
from utils.logger import get_logger

log = get_logger("quality_scorer")

HIGH_RELIABILITY_DOMAINS = [
    "aws.amazon.com",
    "cloud.google.com",
    "github.com",
    "azure.microsoft.com",
    "status.io",
    "statuspage.io",
]
ENGINEERING_BLOG_RE = re.compile(r"engineering\.")

ERROR_CODE_RE = re.compile(
    r"HTTP\s*[45]\d{2}|OOMKilled|ETIMEDOUT|ECONNREFUSED|\b50[0234]\b|\b404\b",
    re.IGNORECASE,
)
METRIC_KEYWORDS = ["latency", "error rate", "throughput", "p99", "p95", "p50", "qps", "rps", "uptime"]
INFRA_KEYWORDS = [
    "database", "cache", "queue", "load balancer", "dns", "certificate",
    "redis", "postgres", "mysql", "kafka", "elasticsearch", "kubernetes", "docker",
]
MAX_EXPECTED_SIGNALS = 5

# Weights must sum to 1.0
WEIGHT_COMPLETENESS = 0.40
WEIGHT_SPECIFICITY = 0.30
WEIGHT_LENGTH = 0.20
WEIGHT_RELIABILITY = 0.10


def _completeness(record: IncidentRecord) -> float:
    checks = [
        bool(record.title),
        bool(record.description),
        bool(record.source_url),
        bool(record.date),
        bool(record.affected_services),
        bool(record.root_causes_raw),
        bool(record.remediation_actions_raw),
        record.duration_minutes is not None,
    ]
    return sum(checks) / len(checks)


def _specificity(record: IncidentRecord) -> float:
    if not record.description:
        return 0.0
    desc = record.description
    desc_lower = desc.lower()
    signals = 0

    if ERROR_CODE_RE.search(desc):
        signals += 1
    if any(kw in desc_lower for kw in METRIC_KEYWORDS):
        signals += 1
    if any(kw in desc_lower for kw in INFRA_KEYWORDS):
        signals += 1
    if re.search(r"\d+%|\d+\s*(?:ms|seconds?|minutes?|hours?)", desc, re.IGNORECASE):
        signals += 1
    # Presence of multiple specific proper nouns
    proper_nouns = re.findall(r"(?<!\.\s)(?<!\n)[A-Z][a-z]{2,}", desc)
    if len(proper_nouns) >= 3:
        signals += 1

    return min(signals / MAX_EXPECTED_SIGNALS, 1.0)


def _description_length(record: IncidentRecord) -> float:
    if not record.description:
        return 0.0
    return min(len(record.description) / 500, 1.0)


def _source_reliability(record: IncidentRecord) -> float:
    if not record.source_url:
        return 0.0
    try:
        domain = urlparse(record.source_url).netloc.lower()
    except Exception:
        return 0.0

    for reliable in HIGH_RELIABILITY_DOMAINS:
        if domain == reliable or domain.endswith("." + reliable):
            return 1.0
    if ENGINEERING_BLOG_RE.search(domain):
        return 1.0
    return 0.7  # URL present but unknown domain


def score(record: IncidentRecord, config: dict) -> IncidentRecord:
    """Assign a quality_score and low_quality flag to an IncidentRecord.

    Score is a weighted average:
      40% completeness — how many expected fields are populated
      30% specificity  — presence of technical detail (error codes, metrics, infra terms)
      20% length       — description length as a proxy for detail level
      10% reliability  — whether source URL is a known high-quality domain

    Records below minimum_score_threshold are flagged with low_quality=True
    but are still stored — downstream components treat them with lower confidence.

    Args:
        record: IncidentRecord to score (mutated in place).
        config: Full application config dict.

    Returns:
        The same record with quality_score and low_quality set.
    """
    min_threshold = config.get("quality", {}).get("minimum_score_threshold", 0.3)

    c = _completeness(record)
    s = _specificity(record)
    l = _description_length(record)
    r = _source_reliability(record)

    quality_score = round(
        c * WEIGHT_COMPLETENESS
        + s * WEIGHT_SPECIFICITY
        + l * WEIGHT_LENGTH
        + r * WEIGHT_RELIABILITY,
        3,
    )

    record.quality_score = quality_score
    record.low_quality = quality_score < min_threshold

    log.debug(
        "Quality score computed",
        record_id=record.id,
        quality_score=quality_score,
        completeness=round(c, 3),
        specificity=round(s, 3),
        length=round(l, 3),
        reliability=round(r, 3),
        low_quality=record.low_quality,
    )

    return record
