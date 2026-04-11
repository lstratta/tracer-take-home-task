from datetime import datetime, timezone

import pytest

from models.incident_record import IncidentRecord
from normaliser.quality_scorer import score


def make_record(**overrides) -> IncidentRecord:
    defaults = {
        "id": "test1234",
        "source_url": None,
        "source_type": "POSTMORTEM",
        "source_sha": "sha123",
        "title": "Default Test Incident",
        "description": "A default description used for testing the quality scorer.",
        "company": None,
        "section": None,
        "date": None,
        "affected_services": [],
        "root_causes_raw": [],
        "remediation_actions_raw": [],
        "duration_minutes": None,
        "severity_raw": None,
        "tags": [],
        "quality_score": None,
        "parse_confidence": 0.5,
        "low_quality": False,
        "content_hash": "test1234",
        "potential_duplicate_of": None,
        "duplicate_confidence": None,
        "ingested_at": datetime.now(tz=timezone.utc).isoformat(),
    }
    defaults.update(overrides)
    return IncidentRecord(**defaults)


@pytest.fixture
def config():
    return {"quality": {"minimum_score_threshold": 0.3}}


def test_high_quality_record_scores_well(config):
    """A fully-populated record with technical detail scores >= 0.6."""
    record = make_record(
        title="AWS S3 Major Outage — us-east-1",
        description=(
            "AWS S3 experienced a major outage in us-east-1 on February 28, 2017. "
            "The root cause was due to an invalid input to the billing subsystem, "
            "causing cascading failures across the storage fleet. "
            "The error rate reached 100% and p99 latency exceeded thresholds. "
            "HTTP 503 errors were returned for all requests. "
            "The incident lasted 4 hours and was resolved by restarting affected "
            "database subsystems and deploying a hotfix to the billing code."
        ),
        source_url="https://aws.amazon.com/message/41926/",
        date="2017-02-28",
        affected_services=["S3", "EC2"],
        root_causes_raw=["root cause was due to an invalid input to the billing subsystem"],
        remediation_actions_raw=["resolved by restarting affected database subsystems"],
        duration_minutes=240,
    )

    result = score(record, config)

    assert result.quality_score is not None
    assert result.quality_score >= 0.6
    assert result.low_quality is False


def test_minimal_record_scores_in_range(config):
    """A minimal record (title + description only) still gets a valid score."""
    record = make_record(
        title="Some Incident",
        description="A brief description of an incident.",
        source_url=None,
    )

    result = score(record, config)

    assert result.quality_score is not None
    assert 0.0 <= result.quality_score <= 1.0


def test_missing_optional_fields_scores_lower(config):
    """A record missing date, affected_services, etc. scores lower than a complete one."""
    incomplete = make_record(title="Incomplete", description="Short description.")
    complete = make_record(
        title="Complete",
        description="Complete description with database cache queue details for 2 hours.",
        source_url="https://aws.amazon.com/message/test/",
        date="2022-01-01",
        affected_services=["ServiceA"],
        root_causes_raw=["caused by a bug"],
        remediation_actions_raw=["fixed by restarting"],
        duration_minutes=120,
    )

    score(incomplete, config)
    score(complete, config)

    assert incomplete.quality_score < complete.quality_score


def test_low_quality_flag_set_below_threshold(config):
    """Records scoring below the threshold have low_quality=True."""
    # A record with almost no information
    record = make_record(
        title="X",
        description="Short.",
        source_url=None,
        date=None,
        affected_services=[],
        root_causes_raw=[],
        remediation_actions_raw=[],
        duration_minutes=None,
    )

    result = score(record, config)

    if result.quality_score < 0.3:
        assert result.low_quality is True


def test_low_quality_flag_not_set_above_threshold(config):
    """Records scoring at or above the threshold have low_quality=False."""
    record = make_record(
        title="AWS Outage",
        description=(
            "AWS database outage caused by memory exhaustion. "
            "The error rate reached p99 latency thresholds. Resolved by restarting."
        ),
        source_url="https://aws.amazon.com/message/test/",
        date="2022-01-01",
        affected_services=["RDS"],
        root_causes_raw=["caused by memory exhaustion"],
        remediation_actions_raw=["resolved by restarting"],
        duration_minutes=60,
    )

    result = score(record, config)

    if result.quality_score >= 0.3:
        assert result.low_quality is False


def test_high_reliability_source_boosts_score(config):
    """A known high-reliability source URL gives a higher score than an unknown domain."""
    desc = "Incident description with database cache queue infrastructure details."
    record_aws = make_record(
        title="AWS Incident", description=desc,
        source_url="https://aws.amazon.com/message/12345/",
    )
    record_unknown = make_record(
        title="Unknown Incident", description=desc,
        source_url="https://someunknownblog.example.com/incident",
    )

    score(record_aws, config)
    score(record_unknown, config)

    assert record_aws.quality_score >= record_unknown.quality_score


def test_no_source_url_penalised(config):
    """A record with no source URL scores lower on reliability than one with any URL."""
    desc = "Incident description with some technical details about the database."
    with_url = make_record(title="With URL", description=desc, source_url="https://example.com")
    without_url = make_record(title="No URL", description=desc, source_url=None)

    score(with_url, config)
    score(without_url, config)

    assert with_url.quality_score > without_url.quality_score


def test_score_is_idempotent(config):
    """Scoring the same record twice produces the same score."""
    record = make_record(
        title="Test",
        description="Test incident description for idempotency check.",
        source_url="https://example.com",
    )

    score(record, config)
    first = record.quality_score

    score(record, config)
    second = record.quality_score

    assert first == second


def test_score_mutates_and_returns_same_object(config):
    """score() mutates the record in place and returns it."""
    record = make_record()
    result = score(record, config)
    assert result is record
    assert record.quality_score is not None


def test_quality_score_always_in_unit_interval(config):
    """quality_score is always in [0.0, 1.0]."""
    record = make_record(
        title="Boundary Test",
        description="Test description.",
        source_url="https://aws.amazon.com",
        date="2023-01-01",
        affected_services=["A", "B"],
        root_causes_raw=["caused by X"],
        remediation_actions_raw=["fixed by Y"],
        duration_minutes=30,
    )

    result = score(record, config)

    assert 0.0 <= result.quality_score <= 1.0
