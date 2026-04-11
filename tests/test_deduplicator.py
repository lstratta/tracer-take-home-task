from datetime import datetime, timezone

import pytest

from models.incident_record import IncidentRecord
from normaliser.deduplicator import _hamming_distance, deduplicate


def make_record(**overrides) -> IncidentRecord:
    defaults = {
        "id": "abcd1234",
        "source_url": "https://example.com/postmortem",
        "source_type": "POSTMORTEM",
        "source_sha": "sha123",
        "title": "Example Incident",
        "description": "A sample incident description for testing deduplication logic.",
        "company": "Example Corp",
        "section": "example",
        "date": "2021-01-01",
        "affected_services": [],
        "root_causes_raw": [],
        "remediation_actions_raw": [],
        "duration_minutes": None,
        "severity_raw": None,
        "tags": [],
        "quality_score": 0.7,
        "parse_confidence": 0.8,
        "low_quality": False,
        "content_hash": "abcd1234",
        "potential_duplicate_of": None,
        "duplicate_confidence": None,
        "ingested_at": datetime.now(tz=timezone.utc).isoformat(),
    }
    defaults.update(overrides)
    return IncidentRecord(**defaults)


@pytest.fixture
def config():
    return {"normalisation": {"dedup_similarity_threshold": 0.9}}


# --- Exact duplicate tests ---

def test_exact_duplicate_removed(config):
    """Two records with the same content_hash — one is removed."""
    r1 = make_record(id="rec00001", content_hash="samehash1")
    r2 = make_record(id="rec00002", content_hash="samehash1")

    result = deduplicate([r1, r2], config)

    assert result.exact_duplicates_removed == 1
    assert len(result.records) == 1


def test_exact_duplicate_keeps_higher_confidence(config):
    """When content_hash matches, the higher parse_confidence record is kept."""
    low = make_record(id="rec00001", content_hash="samehash2", parse_confidence=0.3)
    high = make_record(id="rec00002", content_hash="samehash2", parse_confidence=0.9)

    result = deduplicate([low, high], config)

    assert len(result.records) == 1
    assert result.records[0].parse_confidence == 0.9


def test_exact_duplicate_pair_recorded(config):
    """Duplicate pairs are captured in the result."""
    r1 = make_record(id="rec00001", content_hash="dupehash9")
    r2 = make_record(id="rec00002", content_hash="dupehash9")

    result = deduplicate([r1, r2], config)

    assert len(result.duplicate_pairs) >= 1
    ids_in_pairs = {id_ for pair in result.duplicate_pairs for id_ in pair}
    assert "rec00001" in ids_in_pairs or "rec00002" in ids_in_pairs


def test_no_duplicates_unchanged(config):
    """A list with no duplicates passes through with counts at zero."""
    records = [
        make_record(id="rec00001", content_hash="hash0001", source_url="https://a.com"),
        make_record(id="rec00002", content_hash="hash0002", source_url="https://b.com"),
        make_record(id="rec00003", content_hash="hash0003", source_url="https://c.com"),
    ]

    result = deduplicate(records, config)

    assert result.exact_duplicates_removed == 0
    assert len(result.records) == 3


def test_empty_list(config):
    """Empty input returns empty output with zero counts."""
    result = deduplicate([], config)

    assert result.records == []
    assert result.exact_duplicates_removed == 0
    assert result.near_duplicates_flagged == 0
    assert result.duplicate_pairs == []


# --- Near-duplicate tests ---

def test_near_duplicate_both_records_kept(config):
    """Near-duplicate records are flagged but both remain in the output."""
    text = "AWS S3 outage caused by a software bug in the storage system in us-east-1"
    r1 = make_record(
        id="rec00001", content_hash="neardup1",
        title="AWS S3 Outage", description=text,
    )
    r2 = make_record(
        id="rec00002", content_hash="neardup2",
        title="AWS S3 Outage", description=text,
    )

    result = deduplicate([r1, r2], config)

    assert len(result.records) == 2


def test_near_duplicate_flagged_with_id(config):
    """Near-duplicate records have potential_duplicate_of set to the other record's ID."""
    text = "Database outage caused by memory exhaustion on the primary server"
    r1 = make_record(id="rec00001", content_hash="ndhash1", title="DB Outage", description=text)
    r2 = make_record(id="rec00002", content_hash="ndhash2", title="DB Outage", description=text)

    result = deduplicate([r1, r2], config)

    flagged = [r for r in result.records if r.potential_duplicate_of is not None]
    assert len(flagged) >= 1


# --- Cross-run deduplication is handled in JsonStore, not here ---

# --- Utility function tests ---

def test_hamming_distance_identical():
    assert _hamming_distance(12345, 12345) == 0


def test_hamming_distance_one_bit():
    assert _hamming_distance(0b1000, 0b1001) == 1


def test_hamming_distance_all_different():
    assert _hamming_distance(0, 0xFFFFFFFF) == 32
