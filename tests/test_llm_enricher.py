from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from enricher.llm_enricher import IncidentExtraction, _format_taxonomy, enrich
from models.incident_record import IncidentRecord


def make_record(**overrides) -> IncidentRecord:
    defaults = {
        "id": "test-record-001",
        "source_url": "https://example.com/postmortem",
        "source_type": "POSTMORTEM",
        "source_sha": "sha456",
        "title": "Original Title",
        "description": "Original description of the incident.",
        "company": "Example Corp",
        "section": "infrastructure",
        "date": "2023-06-01",
        "affected_services": ["OldService"],
        "root_causes_raw": ["Old root cause"],
        "remediation_actions_raw": ["Old remediation"],
        "duration_minutes": None,
        "severity_raw": None,
        "tags": [],
        "quality_score": None,
        "parse_confidence": 0.6,
        "low_quality": False,
        "content_hash": "testhash001",
        "potential_duplicate_of": None,
        "duplicate_confidence": None,
        "ingested_at": datetime.now(tz=timezone.utc).isoformat(),
    }
    defaults.update(overrides)
    return IncidentRecord(**defaults)


def make_mock_llm(extraction: IncidentExtraction):
    mock_llm = MagicMock()
    mock_structured = MagicMock()
    mock_llm.with_structured_output.return_value = mock_structured
    mock_structured.invoke.return_value = extraction
    return mock_llm


# --- _format_taxonomy tests ---

def test_format_taxonomy_renders_correctly():
    """Category, subcategory, and types are rendered as indented text."""
    taxonomy = {
        "infrastructure": {
            "network": ["latency", "partition"],
            "compute": ["cpu_saturation"],
        }
    }

    result = _format_taxonomy(taxonomy)

    assert "  infrastructure:" in result
    assert "    network: latency, partition" in result
    assert "    compute: cpu_saturation" in result


def test_format_taxonomy_empty_dict():
    """An empty taxonomy dict returns an empty string."""
    result = _format_taxonomy({})

    assert result == ""


def test_format_taxonomy_category_with_no_subcategories():
    """A category with an empty subcategory dict doesn't crash."""
    taxonomy = {
        "operational": {},
    }

    result = _format_taxonomy(taxonomy)

    assert "  operational:" in result
    # No subcategory lines should follow — no crash
    lines = result.splitlines()
    assert all("    " not in line for line in lines)


# --- enrich tests ---

def test_enrich_updates_core_fields():
    """enrich() overwrites title, description, affected_services, root_causes, and remediation."""
    extraction = IncidentExtraction(
        title="Updated Title",
        summary="A clear summary.",
        affected_services=["ServiceA"],
        root_causes=["A bug"],
        remediation_actions=["Fixed it"],
    )
    record = make_record()
    mock_llm = make_mock_llm(extraction)

    result = enrich(record, "page content", mock_llm, {})

    assert result.title == "Updated Title"
    assert result.description == "A clear summary."
    assert result.affected_services == ["ServiceA"]
    assert result.root_causes_raw == ["A bug"]
    assert result.remediation_actions_raw == ["Fixed it"]


def test_enrich_sets_llm_enriched_flag_and_timestamp():
    """enrich() sets llm_enriched=True and llm_enriched_at to a non-empty ISO string."""
    extraction = IncidentExtraction(
        title="Updated Title",
        summary="A clear summary.",
        affected_services=["ServiceA"],
        root_causes=["A bug"],
        remediation_actions=["Fixed it"],
    )
    record = make_record()
    mock_llm = make_mock_llm(extraction)

    result = enrich(record, "page content", mock_llm, {})

    assert result.llm_enriched is True
    assert result.llm_enriched_at is not None
    assert len(result.llm_enriched_at) > 0
    # Should parse as a valid ISO timestamp
    datetime.fromisoformat(result.llm_enriched_at)


def test_enrich_does_not_overwrite_fields_when_extraction_returns_empty():
    """enrich() keeps existing field values when the LLM returns empty lists or None."""
    extraction = IncidentExtraction(
        title="Updated Title",
        summary="A clear summary.",
        affected_services=[],       # empty — should not overwrite
        root_causes=[],             # empty — should not overwrite
        remediation_actions=[],     # empty — should not overwrite
        duration_minutes=None,
        severity=None,
        date=None,
    )
    record = make_record(
        affected_services=["OriginalService"],
        root_causes_raw=["Original root cause"],
        remediation_actions_raw=["Original remediation"],
        duration_minutes=90,
        severity_raw="partial outage",
        date="2023-01-15",
    )
    mock_llm = make_mock_llm(extraction)

    result = enrich(record, "page content", mock_llm, {})

    assert result.affected_services == ["OriginalService"]
    assert result.root_causes_raw == ["Original root cause"]
    assert result.remediation_actions_raw == ["Original remediation"]
    assert result.duration_minutes == 90
    assert result.severity_raw == "partial outage"
    assert result.date == "2023-01-15"


def test_enrich_copies_taxonomy_fields():
    """enrich() writes taxonomy_category, subcategory, type, and justification to record."""
    extraction = IncidentExtraction(
        title="Updated Title",
        summary="A clear summary.",
        affected_services=["ServiceA"],
        root_causes=["A bug"],
        remediation_actions=["Fixed it"],
        taxonomy_category="infrastructure",
        taxonomy_subcategory="network",
        taxonomy_type="latency",
        taxonomy_justification="Network issues caused the incident.",
    )
    record = make_record()
    mock_llm = make_mock_llm(extraction)

    result = enrich(record, "page content", mock_llm, {})

    assert result.taxonomy_category == "infrastructure"
    assert result.taxonomy_subcategory == "network"
    assert result.taxonomy_type == "latency"
    assert result.taxonomy_justification == "Network issues caused the incident."


def test_enrich_returns_record_unchanged_on_llm_exception():
    """enrich() returns the original record unmodified when the LLM raises an exception."""
    record = make_record()
    mock_llm = MagicMock()
    mock_structured = MagicMock()
    mock_llm.with_structured_output.return_value = mock_structured
    mock_structured.invoke.side_effect = RuntimeError("LLM connection failed")

    result = enrich(record, "page content", mock_llm, {})

    assert result is record
    assert result.llm_enriched is False
    assert result.llm_enriched_at is None
    assert result.title == "Original Title"
    assert result.description == "Original description of the incident."


def test_enrich_sets_llm_summary_separately_from_description():
    """enrich() sets llm_summary in addition to updating description with the summary text."""
    summary_text = "A clear and detailed LLM-written summary."
    extraction = IncidentExtraction(
        title="Updated Title",
        summary=summary_text,
        affected_services=["ServiceA"],
        root_causes=["A bug"],
        remediation_actions=["Fixed it"],
    )
    record = make_record()
    mock_llm = make_mock_llm(extraction)

    result = enrich(record, "page content", mock_llm, {})

    assert result.llm_summary == summary_text
    assert result.description == summary_text
    assert result.llm_summary == result.description


def test_enrich_passes_taxonomy_block_from_config():
    """enrich() uses the taxonomy from config when constructing the LLM prompt."""
    extraction = IncidentExtraction(
        title="Updated Title",
        summary="A clear summary.",
        affected_services=["ServiceA"],
        root_causes=["A bug"],
        remediation_actions=["Fixed it"],
    )
    record = make_record()
    mock_llm = MagicMock()
    mock_structured = MagicMock()
    mock_llm.with_structured_output.return_value = mock_structured
    mock_structured.invoke.return_value = extraction

    config = {
        "taxonomy": {
            "infrastructure": {
                "network": ["latency", "partition"],
            }
        }
    }

    enrich(record, "page content", mock_llm, config)

    # with_structured_output should have been called once
    mock_llm.with_structured_output.assert_called_once_with(IncidentExtraction)
    # invoke should have been called once with a messages list
    mock_structured.invoke.assert_called_once()
    messages = mock_structured.invoke.call_args[0][0]
    # The human message content should contain the formatted taxonomy
    human_message_content = messages[1].content
    assert "infrastructure:" in human_message_content
    assert "network:" in human_message_content


def test_enrich_full_extraction_with_full_mock():
    """Integration-style test: full mock extraction matches all fields on the record."""
    mock_llm = MagicMock()
    mock_structured = MagicMock()
    mock_llm.with_structured_output.return_value = mock_structured
    mock_structured.invoke.return_value = IncidentExtraction(
        title="Updated Title",
        summary="A clear summary.",
        affected_services=["ServiceA"],
        root_causes=["A bug"],
        remediation_actions=["Fixed it"],
        taxonomy_category="infrastructure",
        taxonomy_subcategory="network",
        taxonomy_type="latency",
        taxonomy_justification="Network issues caused the incident.",
    )

    record = make_record()
    result = enrich(record, "page content", mock_llm, {})

    assert result.title == "Updated Title"
    assert result.description == "A clear summary."
    assert result.llm_summary == "A clear summary."
    assert result.affected_services == ["ServiceA"]
    assert result.root_causes_raw == ["A bug"]
    assert result.remediation_actions_raw == ["Fixed it"]
    assert result.taxonomy_category == "infrastructure"
    assert result.taxonomy_subcategory == "network"
    assert result.taxonomy_type == "latency"
    assert result.taxonomy_justification == "Network issues caused the incident."
    assert result.llm_enriched is True
    assert result.llm_enriched_at is not None
