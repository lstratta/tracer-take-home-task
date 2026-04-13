"""Tests for enricher/batch.py — run_batch() pipeline."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from enricher.batch import BatchEnrichmentResult, run_batch
from models.incident_record import IncidentRecord
from storage.json_store import JsonStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_record(**overrides) -> IncidentRecord:
    defaults = {
        "id": "ab1234567890abcd",
        "source_url": "https://example.com/postmortem",
        "source_type": "POSTMORTEM",
        "source_sha": "sha123",
        "title": "Example Incident",
        "description": "A sample incident description for testing the batch enricher.",
        "company": "Example Corp",
        "section": "example",
        "date": "2022-01-01",
        "affected_services": [],
        "root_causes_raw": [],
        "remediation_actions_raw": [],
        "duration_minutes": None,
        "severity_raw": None,
        "tags": [],
        "quality_score": 0.5,
        "parse_confidence": 0.8,
        "low_quality": False,
        "content_hash": "ab1234567890abcd",
        "potential_duplicate_of": None,
        "duplicate_confidence": None,
        "ingested_at": datetime.now(tz=timezone.utc).isoformat(),
    }
    defaults.update(overrides)
    return IncidentRecord(**defaults)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def config(tmp_path):
    return {
        "storage": {
            "output_directory": str(tmp_path / "incidents"),
            "index_file": str(tmp_path / "index.json"),
            "run_state_file": str(tmp_path / "run_state.json"),
            "overwrite_existing": False,
        },
        "enrichment": {
            "min_parse_confidence": 0.3,
            "request_timeout_seconds": 10,
            "max_content_chars": 1000,
        },
    }


@pytest.fixture
def store(config):
    return JsonStore(config)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_empty_result_when_no_unenriched_candidates(config, store):
    """Returns an empty BatchEnrichmentResult when all records are already enriched."""
    record = make_record(id="ab0000000001abcd", content_hash="ab0000000001abcd")
    store.save_all([record])

    # Mark the record as already enriched in the index
    index = store.load_index()
    index["records"][0]["llm_enriched"] = True
    store._save_index(index)

    with patch("enricher.batch.build_llm") as mock_build_llm, \
         patch("enricher.batch.fetch_content") as mock_fetch, \
         patch("enricher.batch.enrich") as mock_enrich, \
         patch("enricher.batch.score") as mock_score:

        result = run_batch(
            config=config,
            api_key="test-key",
            store=store,
            count=10,
            enrich_all=False,
            force=False,
        )

    assert isinstance(result, BatchEnrichmentResult)
    assert result.enriched == 0
    assert result.skipped == 0
    assert result.errors == 0
    assert result.record_results == []
    mock_build_llm.assert_not_called()
    mock_fetch.assert_not_called()
    mock_enrich.assert_not_called()
    mock_score.assert_not_called()


def test_skips_record_with_no_source_url(config, store):
    """A record whose source_url is None is skipped with reason 'no valid source URL'."""
    record = make_record(
        id="ab0000000002abcd",
        content_hash="ab0000000002abcd",
        source_url=None,
        title="No URL Incident",
    )
    store.save_all([record])

    with patch("enricher.batch.build_llm") as mock_build_llm, \
         patch("enricher.batch.fetch_content") as mock_fetch, \
         patch("enricher.batch.enrich") as mock_enrich, \
         patch("enricher.batch.score") as mock_score:

        result = run_batch(
            config=config,
            api_key="test-key",
            store=store,
            count=10,
            enrich_all=False,
            force=False,
        )

    assert result.enriched == 0
    assert result.skipped == 1
    assert result.errors == 0
    assert len(result.record_results) == 1
    rr = result.record_results[0]
    assert rr.record_id == record.id
    assert rr.status == "skip"
    assert "source URL" in rr.reason
    mock_fetch.assert_not_called()
    mock_enrich.assert_not_called()
    mock_score.assert_not_called()


def test_skips_record_below_min_parse_confidence(config, store):
    """A record with parse_confidence below the threshold is skipped."""
    record = make_record(
        id="ab0000000003abcd",
        content_hash="ab0000000003abcd",
        source_url="https://example.com/postmortem",
        parse_confidence=0.1,   # below the 0.3 threshold in config
    )
    store.save_all([record])

    with patch("enricher.batch.build_llm"), \
         patch("enricher.batch.fetch_content") as mock_fetch, \
         patch("enricher.batch.enrich") as mock_enrich, \
         patch("enricher.batch.score") as mock_score:

        result = run_batch(
            config=config,
            api_key="test-key",
            store=store,
            count=10,
            enrich_all=False,
            force=False,
        )

    assert result.skipped == 1
    assert result.enriched == 0
    assert result.errors == 0
    rr = result.record_results[0]
    assert rr.status == "skip"
    assert "confidence" in rr.reason
    mock_fetch.assert_not_called()
    mock_enrich.assert_not_called()
    mock_score.assert_not_called()


def test_skips_record_when_fetch_content_returns_none(config, store):
    """A record is skipped when fetch_content returns None."""
    record = make_record(
        id="ab0000000004abcd",
        content_hash="ab0000000004abcd",
        source_url="https://example.com/postmortem",
        parse_confidence=0.9,
    )
    store.save_all([record])

    with patch("enricher.batch.build_llm"), \
         patch("enricher.batch.fetch_content", return_value=None) as mock_fetch, \
         patch("enricher.batch.enrich") as mock_enrich, \
         patch("enricher.batch.score") as mock_score:

        result = run_batch(
            config=config,
            api_key="test-key",
            store=store,
            count=10,
            enrich_all=False,
            force=False,
        )

    assert result.skipped == 1
    assert result.enriched == 0
    assert result.errors == 0
    rr = result.record_results[0]
    assert rr.status == "skip"
    mock_fetch.assert_called_once_with(record.source_url, config)
    mock_enrich.assert_not_called()
    mock_score.assert_not_called()


def test_enriches_record_successfully(config, store):
    """A valid record is enriched: enriched=1, status='ok', enrich/score/update_record called."""
    record = make_record(
        id="ab0000000005abcd",
        content_hash="ab0000000005abcd",
        source_url="https://example.com/postmortem",
        parse_confidence=0.9,
    )
    store.save_all([record])

    fake_llm = MagicMock()
    page_content = "The page content of the incident report."

    with patch("enricher.batch.build_llm", return_value=fake_llm) as mock_build_llm, \
         patch("enricher.batch.fetch_content", return_value=page_content) as mock_fetch, \
         patch("enricher.batch.enrich") as mock_enrich, \
         patch("enricher.batch.score") as mock_score:

        result = run_batch(
            config=config,
            api_key="test-key",
            store=store,
            count=10,
            enrich_all=False,
            force=False,
        )

    assert result.enriched == 1
    assert result.skipped == 0
    assert result.errors == 0
    assert len(result.record_results) == 1
    rr = result.record_results[0]
    assert rr.record_id == record.id
    assert rr.status == "ok"

    mock_build_llm.assert_called_once_with(config, "test-key")
    mock_fetch.assert_called_once_with(record.source_url, config)
    # enrich and score receive the loaded record object
    mock_enrich.assert_called_once()
    enrich_args = mock_enrich.call_args
    assert enrich_args.args[1] == page_content
    assert enrich_args.args[2] is fake_llm
    assert enrich_args.args[3] == config
    mock_score.assert_called_once()


def test_records_error_when_enrich_raises(config, store):
    """When enrich() raises an exception the error count increments and status is 'error'."""
    record = make_record(
        id="ab0000000006abcd",
        content_hash="ab0000000006abcd",
        source_url="https://example.com/postmortem",
        parse_confidence=0.9,
    )
    store.save_all([record])

    boom = RuntimeError("LLM exploded")

    with patch("enricher.batch.build_llm", return_value=MagicMock()), \
         patch("enricher.batch.fetch_content", return_value="some content"), \
         patch("enricher.batch.enrich", side_effect=boom), \
         patch("enricher.batch.score") as mock_score:

        result = run_batch(
            config=config,
            api_key="test-key",
            store=store,
            count=10,
            enrich_all=False,
            force=False,
        )

    assert result.errors == 1
    assert result.enriched == 0
    assert len(result.record_results) == 1
    rr = result.record_results[0]
    assert rr.record_id == record.id
    assert rr.status == "error"
    assert "LLM exploded" in rr.reason
    mock_score.assert_not_called()


def test_incident_id_not_found_returns_error(config, store):
    """Passing an incident_id that does not exist in the index returns an error result."""
    record = make_record(
        id="ab0000000007abcd",
        content_hash="ab0000000007abcd",
    )
    store.save_all([record])

    with patch("enricher.batch.build_llm"), \
         patch("enricher.batch.fetch_content"), \
         patch("enricher.batch.enrich"), \
         patch("enricher.batch.score"):

        result = run_batch(
            config=config,
            api_key="test-key",
            store=store,
            count=10,
            enrich_all=False,
            force=False,
            incident_id="nonexistent-id-xyz",
        )

    assert result.errors == 1
    assert result.enriched == 0
    assert result.skipped == 0
    assert len(result.record_results) == 1
    rr = result.record_results[0]
    assert rr.record_id == "nonexistent-id-xyz"
    assert rr.status == "error"
    assert "not found in index" in rr.reason


def test_incident_id_already_enriched_without_force_skips(config, store):
    """When targeting an already-enriched record with force=False, the record is skipped."""
    record = make_record(
        id="ab0000000008abcd",
        content_hash="ab0000000008abcd",
        source_url="https://example.com/postmortem",
    )
    store.save_all([record])

    # Manually mark the index entry as already enriched
    index = store.load_index()
    index["records"][0]["llm_enriched"] = True
    store._save_index(index)

    with patch("enricher.batch.build_llm") as mock_build_llm, \
         patch("enricher.batch.fetch_content") as mock_fetch, \
         patch("enricher.batch.enrich") as mock_enrich, \
         patch("enricher.batch.score") as mock_score:

        result = run_batch(
            config=config,
            api_key="test-key",
            store=store,
            count=10,
            enrich_all=False,
            force=False,
            incident_id=record.id,
        )

    assert result.skipped == 1
    assert result.enriched == 0
    assert result.errors == 0
    assert len(result.record_results) == 1
    rr = result.record_results[0]
    assert rr.record_id == record.id
    assert rr.status == "skip"
    assert "already enriched" in rr.reason
    mock_build_llm.assert_not_called()
    mock_fetch.assert_not_called()
    mock_enrich.assert_not_called()
    mock_score.assert_not_called()


def test_incident_id_processes_exact_record(config, store):
    """When incident_id is set, only that specific record is processed, not others."""
    target = make_record(
        id="ab0000000009abcd",
        content_hash="ab0000000009abcd",
        source_url="https://example.com/target",
        parse_confidence=0.9,
    )
    other = make_record(
        id="cd0000000009cdcd",
        content_hash="cd0000000009cdcd",
        source_url="https://example.com/other",
        parse_confidence=0.9,
    )
    store.save_all([target, other])

    fake_llm = MagicMock()

    with patch("enricher.batch.build_llm", return_value=fake_llm), \
         patch("enricher.batch.fetch_content", return_value="page content") as mock_fetch, \
         patch("enricher.batch.enrich") as mock_enrich, \
         patch("enricher.batch.score") as mock_score:

        result = run_batch(
            config=config,
            api_key="test-key",
            store=store,
            count=10,
            enrich_all=False,
            force=False,
            incident_id=target.id,
        )

    assert result.enriched == 1
    assert result.skipped == 0
    assert result.errors == 0
    assert len(result.record_results) == 1
    rr = result.record_results[0]
    assert rr.record_id == target.id
    assert rr.status == "ok"

    # fetch_content was only called for the target URL, not the other record
    mock_fetch.assert_called_once_with(target.source_url, config)
    mock_enrich.assert_called_once()
    mock_score.assert_called_once()
