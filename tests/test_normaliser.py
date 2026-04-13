from datetime import datetime, timezone

import pytest
import pydantic

from models.raw_incident import RawIncident
from models.incident_record import IncidentRecord
from normaliser.normaliser import normalise, DANLUU_REPO_URL


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_raw(**overrides) -> RawIncident:
    """Return a RawIncident with sensible defaults that always produce a valid record."""
    defaults = dict(
        raw_text="AWS S3 experienced a major outage.",
        section="Amazon",
        company_or_service="Amazon S3",
        primary_url="https://aws.amazon.com/message/41926/",
        secondary_urls=[],
        description_raw="AWS S3 experienced a major outage.",
        date_raw="2017-02-28",
        date_parsed=datetime(2017, 2, 28, tzinfo=timezone.utc),
        parse_confidence=0.9,
        line_number=42,
    )
    defaults.update(overrides)
    return RawIncident(**defaults)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def config():
    return {"normalisation": {"dedup_similarity_threshold": 0.9}}


@pytest.fixture
def sha():
    return "deadbeef" * 8  # 64-char hex string


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_returns_incident_record(config, sha):
    """normalise() returns an IncidentRecord instance."""
    raw = make_raw()
    result = normalise(raw, sha, config)
    assert isinstance(result, IncidentRecord)


def test_title_from_company_or_service(config, sha):
    """Title is taken from company_or_service when it is present."""
    raw = make_raw(company_or_service="Cloudflare")
    result = normalise(raw, sha, config)
    assert result.title == "Cloudflare"


def test_title_falls_back_to_first_sentence_of_description(config, sha):
    """Title is the first sentence of description when company_or_service is absent."""
    raw = make_raw(
        company_or_service=None,
        description_raw="The database went down. Recovery took hours.",
    )
    result = normalise(raw, sha, config)
    assert result.title == "The database went down"


def test_source_url_uses_primary_url(config, sha):
    """source_url equals primary_url when primary_url is supplied."""
    url = "https://example.com/postmortem"
    raw = make_raw(primary_url=url)
    result = normalise(raw, sha, config)
    assert result.source_url == url


def test_source_url_falls_back_to_danluu_with_line_anchor(config, sha):
    """source_url falls back to DANLUU_REPO_URL#L{line} when primary_url is absent."""
    raw = make_raw(primary_url=None, line_number=99)
    result = normalise(raw, sha, config)
    assert result.source_url == f"{DANLUU_REPO_URL}#L99"


def test_source_url_danluu_no_anchor_when_no_line(config, sha):
    """source_url is bare DANLUU_REPO_URL when neither primary_url nor line_number exist."""
    raw = make_raw(primary_url=None, line_number=None)
    result = normalise(raw, sha, config)
    assert result.source_url == DANLUU_REPO_URL


def test_section_normalised(config, sha):
    """Section heading is lowercased with non-word characters replaced by underscores."""
    raw = make_raw(section="US East")
    result = normalise(raw, sha, config)
    assert result.section == "us_east"


def test_date_extracted_as_iso_string(config, sha):
    """date field is the ISO 8601 date string derived from date_parsed."""
    raw = make_raw(date_parsed=datetime(2023, 6, 15, tzinfo=timezone.utc))
    result = normalise(raw, sha, config)
    assert result.date == "2023-06-15"


def test_duration_minutes_hours(config, sha):
    """'4 hours' in description is converted to 240 minutes."""
    raw = make_raw(description_raw="The outage lasted 4 hours before recovery.")
    result = normalise(raw, sha, config)
    assert result.duration_minutes == 240


def test_duration_minutes_plain_minutes(config, sha):
    """'90 minutes' in description is stored as 90."""
    raw = make_raw(description_raw="Service was unavailable for 90 minutes.")
    result = normalise(raw, sha, config)
    assert result.duration_minutes == 90


def test_severity_raw_extracted(config, sha):
    """severity_raw lists severity keywords found in the description."""
    raw = make_raw(description_raw="A complete outage hit the primary database.")
    result = normalise(raw, sha, config)
    assert result.severity_raw is not None
    assert "outage" in result.severity_raw


def test_root_causes_raw_captured(config, sha):
    """Sentences containing root-cause keywords are collected in root_causes_raw."""
    raw = make_raw(
        description_raw=(
            "The API went down. "
            "This was caused by a misconfigured load balancer. "
            "Engineers were paged immediately."
        )
    )
    result = normalise(raw, sha, config)
    assert any("caused by" in s.lower() for s in result.root_causes_raw)


def test_remediation_actions_raw_captured(config, sha):
    """Sentences containing remediation keywords are collected in remediation_actions_raw."""
    raw = make_raw(
        description_raw=(
            "The cluster became unavailable. "
            "The issue was resolved by rolling back the deployment. "
            "Monitoring confirmed recovery."
        )
    )
    result = normalise(raw, sha, config)
    assert any("resolved by" in s.lower() for s in result.remediation_actions_raw)


def test_raises_validation_error_when_no_title_and_no_description(config, sha):
    """pydantic.ValidationError is raised when both title and description are absent."""
    raw = make_raw(
        company_or_service=None,
        description_raw=None,
        raw_text="some raw text to keep the id stable",
    )
    with pytest.raises(pydantic.ValidationError):
        normalise(raw, sha, config)


def test_id_is_stable_same_input(config, sha):
    """The same RawIncident always produces the same record ID."""
    raw1 = make_raw()
    raw2 = make_raw()
    assert normalise(raw1, sha, config).id == normalise(raw2, sha, config).id


def test_id_differs_for_different_primary_url(config, sha):
    """Different primary_url values produce different IDs."""
    raw_a = make_raw(primary_url="https://a.example.com/incident-1")
    raw_b = make_raw(primary_url="https://b.example.com/incident-2")
    assert normalise(raw_a, sha, config).id != normalise(raw_b, sha, config).id
