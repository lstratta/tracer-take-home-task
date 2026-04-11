from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from models.incident_record import IncidentRecord
from utils.hashing import compute_simhash
from utils.logger import get_logger

log = get_logger("deduplicator")


def _hamming_distance(a: int, b: int) -> int:
    """Number of bit positions where two integers differ."""
    return bin(a ^ b).count("1")


def _threshold_to_max_bits(threshold: float) -> int:
    """Convert a similarity threshold (0–1) to a max Hamming distance over 64 bits."""
    return int(64 * (1 - threshold))


@dataclass
class DeduplicationResult:
    """Output of a deduplication pass."""

    records: List[IncidentRecord]
    exact_duplicates_removed: int
    near_duplicates_flagged: int
    duplicate_pairs: List[Tuple[str, str]] = field(default_factory=list)


def deduplicate(records: List[IncidentRecord], config: dict) -> DeduplicationResult:
    """Identify and handle duplicate IncidentRecord objects.

    Two passes:
    1. Exact deduplication — records with identical content_hash. The record
       with the higher parse_confidence is kept; the other is removed.
    2. Near-duplicate detection — records with similar SimHash values
       (Hamming distance within threshold). Both records are kept but flagged
       with potential_duplicate_of and duplicate_confidence. This is intentionally
       conservative: it is better to keep a potential duplicate than to discard
       a distinct incident.

    Args:
        records: List of IncidentRecord objects to deduplicate.
        config: Full application config dict.

    Returns:
        DeduplicationResult with deduplicated records and statistics.
    """
    norm_config = config.get("normalisation", {})
    threshold = norm_config.get("dedup_similarity_threshold", 0.9)
    max_bits = _threshold_to_max_bits(threshold)

    # --- Pass 1: Exact deduplication by content_hash ---
    seen: Dict[str, IncidentRecord] = {}
    deduped: List[IncidentRecord] = []
    exact_removed = 0
    duplicate_pairs: List[Tuple[str, str]] = []

    for record in records:
        h = record.content_hash
        if h in seen:
            existing = seen[h]
            log.info(
                "Exact duplicate found",
                record_id=record.id,
                duplicate_of=existing.id,
                content_hash=h,
            )
            duplicate_pairs.append((record.id, existing.id))
            exact_removed += 1
            if record.parse_confidence > existing.parse_confidence:
                deduped.remove(existing)
                deduped.append(record)
                seen[h] = record
        else:
            seen[h] = record
            deduped.append(record)

    # --- Pass 2: Near-duplicate flagging via SimHash ---
    near_flagged = 0
    computed: List[Tuple[IncidentRecord, int]] = []

    for record in deduped:
        text = f"{record.title or ''} {record.description or ''}"
        sh = compute_simhash(text)

        for other, other_sh in computed:
            dist = _hamming_distance(sh, other_sh)
            if dist <= max_bits and record.id != other.id:
                similarity = round(1.0 - dist / 64.0, 3)
                log.info(
                    "Near-duplicate detected",
                    record_id=record.id,
                    similar_to=other.id,
                    hamming_distance=dist,
                    similarity=similarity,
                )
                duplicate_pairs.append((record.id, other.id))
                near_flagged += 1

                record.potential_duplicate_of = other.id
                record.duplicate_confidence = similarity

                if not other.potential_duplicate_of:
                    other.potential_duplicate_of = record.id
                    other.duplicate_confidence = similarity

        computed.append((record, sh))

    log.info(
        "Deduplication complete",
        input_records=len(records),
        output_records=len(deduped),
        exact_duplicates_removed=exact_removed,
        near_duplicates_flagged=near_flagged,
    )

    return DeduplicationResult(
        records=deduped,
        exact_duplicates_removed=exact_removed,
        near_duplicates_flagged=near_flagged,
        duplicate_pairs=duplicate_pairs,
    )
