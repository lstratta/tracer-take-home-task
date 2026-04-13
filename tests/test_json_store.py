import json
import os
from datetime import datetime, timezone

import pytest

from models.incident_record import IncidentRecord
from storage.json_store import JsonStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_record(**overrides) -> IncidentRecord:
    """Return a minimal but valid IncidentRecord, with any field overridable."""
    defaults = {
        "id": "ab1234cd",
        "source_url": "https://example.com/postmortem/1",
        "source_type": "POSTMORTEM",
        "source_sha": "sha_abc123",
        "title": "Example Outage",
        "description": "A sample incident for unit-testing the JsonStore.",
        "company": "Example Corp",
        "section": "database",
        "date": "2023-06-15",
        "affected_services": ["postgres"],
        "root_causes_raw": ["memory exhaustion"],
        "remediation_actions_raw": ["restarted the service"],
        "duration_minutes": 45,
        "severity_raw": "outage",
        "tags": ["database"],
        "quality_score": 0.75,
        "parse_confidence": 0.8,
        "low_quality": False,
        "content_hash": "hashABCD1234",
        "potential_duplicate_of": None,
        "duplicate_confidence": None,
        "ingested_at": datetime.now(tz=timezone.utc).isoformat(),
    }
    defaults.update(overrides)
    return IncidentRecord(**defaults)


@pytest.fixture
def store(tmp_path):
    config = {
        "storage": {
            "output_directory": str(tmp_path / "incidents"),
            "index_file": str(tmp_path / "index.json"),
            "run_state_file": str(tmp_path / "run_state.json"),
            "overwrite_existing": False,
        }
    }
    return JsonStore(config)


@pytest.fixture
def store_overwrite(tmp_path):
    """Store configured with overwrite_existing=True."""
    config = {
        "storage": {
            "output_directory": str(tmp_path / "incidents"),
            "index_file": str(tmp_path / "index.json"),
            "run_state_file": str(tmp_path / "run_state.json"),
            "overwrite_existing": True,
        }
    }
    return JsonStore(config)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_load_index_returns_empty_structure_when_no_file_exists(store):
    """load_index returns the sentinel empty dict when the index file is absent."""
    index = store.load_index()

    assert index["last_updated"] is None
    assert index["total_records"] == 0
    assert index["source_sha"] is None
    assert index["records"] == []


def test_save_record_creates_json_file_on_disk(store):
    """save_record writes a JSON file at the path derived from the record id."""
    record = make_record(id="ab1111aa")
    index = store.load_index()

    store.save_record(record, index)

    expected_path = os.path.join(store.output_directory, "ab", "ab1111aa.json")
    assert os.path.isfile(expected_path), f"Expected file not found: {expected_path}"
    with open(expected_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["id"] == "ab1111aa"


def test_save_record_adds_entry_to_index_and_returns_true(store):
    """save_record returns True and appends a summary entry to the in-memory index."""
    record = make_record(id="ab2222bb")
    index = store.load_index()

    result = store.save_record(record, index)

    assert result is True
    assert index["total_records"] == 1
    assert len(index["records"]) == 1
    entry = index["records"][0]
    assert entry["id"] == "ab2222bb"
    assert entry["source_url"] == record.source_url
    assert entry["content_hash"] == record.content_hash


def test_save_record_skips_duplicate_by_id_and_returns_false(store):
    """When overwrite_existing=False, saving a record with the same id is a no-op."""
    record = make_record(id="ab3333cc")
    index = store.load_index()

    first = store.save_record(record, index)
    second = store.save_record(record, index)

    assert first is True
    assert second is False
    # The index must not have grown a second entry.
    assert index["total_records"] == 1


def test_record_exists_detects_duplicate_by_id(store):
    """record_exists returns True when the index contains a record with the same id."""
    record = make_record(id="ab4444dd", content_hash="unique_hash_id_test")
    index = store.load_index()
    store.save_record(record, index)

    probe = make_record(
        id="ab4444dd",
        source_url="https://different.url/",
        content_hash="completely_different_hash",
    )
    assert store.record_exists(probe, index) is True


def test_record_exists_detects_duplicate_by_source_url(store):
    """record_exists returns True when source_url matches an existing entry."""
    shared_url = "https://example.com/shared-postmortem"
    record = make_record(
        id="ab5555ee",
        source_url=shared_url,
        content_hash="hash_url_test_1",
    )
    index = store.load_index()
    store.save_record(record, index)

    probe = make_record(
        id="ab6666ff",  # different id
        source_url=shared_url,
        content_hash="hash_url_test_2",
    )
    assert store.record_exists(probe, index) is True


def test_record_exists_detects_duplicate_by_content_hash(store):
    """record_exists returns True when content_hash matches an existing entry."""
    shared_hash = "shared_content_hash_xyz"
    record = make_record(
        id="ab7777gg",
        source_url="https://example.com/original",
        content_hash=shared_hash,
    )
    index = store.load_index()
    store.save_record(record, index)

    probe = make_record(
        id="ab8888hh",  # different id
        source_url="https://example.com/mirror",  # different URL
        content_hash=shared_hash,
    )
    assert store.record_exists(probe, index) is True


def test_save_all_returns_correct_saved_and_skipped_counts(store):
    """save_all persists all new records and skips any that already exist."""
    records = [
        make_record(id="ab0001aa", source_url="https://a.example.com/", content_hash="hash_0001"),
        make_record(id="ab0002bb", source_url="https://b.example.com/", content_hash="hash_0002"),
        make_record(id="ab0003cc", source_url="https://c.example.com/", content_hash="hash_0003"),
    ]

    # First batch: all three are new.
    result = store.save_all(records, source_sha="sha_run1")
    assert result == {"saved": 3, "skipped": 0}

    # Second batch: same three records → all skipped.
    result2 = store.save_all(records, source_sha="sha_run2")
    assert result2 == {"saved": 0, "skipped": 3}


def test_load_record_returns_none_for_missing_file(store):
    """load_record returns None rather than raising when the file does not exist."""
    result = store.load_record("nonexistent_record_id")
    assert result is None


def test_load_record_deserialises_a_saved_record(store):
    """load_record round-trips a saved record back to an IncidentRecord instance."""
    original = make_record(
        id="ab9999ii",
        title="Round-Trip Incident",
        description="Testing serialisation fidelity.",
        company="Acme",
        date="2024-01-01",
        quality_score=0.9,
        content_hash="hash_roundtrip",
    )
    index = store.load_index()
    store.save_record(original, index)

    loaded = store.load_record("ab9999ii")

    assert loaded is not None
    assert isinstance(loaded, IncidentRecord)
    assert loaded.id == original.id
    assert loaded.title == original.title
    assert loaded.company == original.company
    assert loaded.quality_score == original.quality_score
    assert loaded.content_hash == original.content_hash


def test_update_record_overwrites_file_even_when_record_exists(store):
    """update_record always writes to disk regardless of overwrite_existing setting."""
    record = make_record(
        id="ab1010jj",
        title="Original Title",
        content_hash="hash_update_test",
    )
    index = store.load_index()
    store.save_record(record, index)

    # Mutate the record and call update_record.
    updated = record.model_copy(update={"title": "Updated Title", "quality_score": 0.99})
    store.update_record(updated, index)

    loaded = store.load_record("ab1010jj")
    assert loaded is not None
    assert loaded.title == "Updated Title"
    assert loaded.quality_score == 0.99


def test_update_record_writes_taxonomy_fields_into_index_entry(store):
    """update_record refreshes the index entry with taxonomy fields."""
    record = make_record(
        id="ab2020kk",
        content_hash="hash_taxonomy_test",
        llm_enriched=False,
        taxonomy_category=None,
        taxonomy_subcategory=None,
        taxonomy_type=None,
    )
    index = store.load_index()
    store.save_record(record, index)

    enriched = record.model_copy(update={
        "llm_enriched": True,
        "taxonomy_category": "infrastructure",
        "taxonomy_subcategory": "compute",
        "taxonomy_type": "oom",
    })
    store.update_record(enriched, index)

    # The in-memory index entry should reflect the enriched values.
    entry = next(e for e in index["records"] if e["id"] == "ab2020kk")
    assert entry["llm_enriched"] is True
    assert entry["taxonomy_category"] == "infrastructure"
    assert entry["taxonomy_subcategory"] == "compute"
    assert entry["taxonomy_type"] == "oom"
