import os
import pytest

from parser.markdown_parser import parse

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "sample_readme.md")


@pytest.fixture
def sample_content():
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def config():
    return {"min_description_length": 50}


def test_standard_entry_parsed(sample_content, config):
    """Entry starting with a hyperlink is parsed into a RawIncident."""
    incidents = parse(sample_content, config)
    assert len(incidents) > 0


def test_primary_url_extracted(sample_content, config):
    """Primary URL is extracted from the first markdown link."""
    incidents = parse(sample_content, config)
    with_url = [i for i in incidents if i.primary_url]
    assert len(with_url) > 0
    assert all(i.primary_url.startswith("http") for i in with_url)


def test_entry_with_multiple_urls(sample_content, config):
    """Entry with multiple URLs populates both primary_url and secondary_urls."""
    incidents = parse(sample_content, config)
    multi_url = [i for i in incidents if i.secondary_urls]
    assert len(multi_url) > 0
    # Company X entry has two secondary URLs
    assert any(len(i.secondary_urls) >= 2 for i in multi_url)


def test_section_headers_assigned(sample_content, config):
    """Section (## heading) is assigned to all subsequent entries."""
    incidents = parse(sample_content, config)
    sections = {i.section for i in incidents if i.section}
    assert "Google" in sections
    assert "Amazon" in sections
    assert "GitHub" in sections
    assert "Cloudflare" in sections


def test_all_incidents_have_line_number(sample_content, config):
    """Every parsed incident has a line_number for traceability."""
    incidents = parse(sample_content, config)
    assert all(i.line_number is not None for i in incidents)
    assert all(isinstance(i.line_number, int) for i in incidents)


def test_raw_text_preserved(sample_content, config):
    """raw_text is populated and non-empty for all incidents."""
    incidents = parse(sample_content, config)
    assert all(i.raw_text for i in incidents)


def test_company_name_extracted(sample_content, config):
    """Company name is extracted from the first link text."""
    incidents = parse(sample_content, config)
    companies = {i.company_or_service for i in incidents if i.company_or_service}
    assert "Cloudflare" in companies
    assert "GitHub" in companies
    assert "Slack" in companies


def test_multiline_entry_joined(sample_content, config):
    """Multi-line entry is joined into a single RawIncident."""
    incidents = parse(sample_content, config)
    multiline = [i for i in incidents if i.company_or_service == "ExampleCorp"]
    assert len(multiline) == 1
    assert "multiple lines" in multiline[0].description_raw.lower()


def test_parse_confidence_in_range(sample_content, config):
    """parse_confidence is always in [0, 1]."""
    incidents = parse(sample_content, config)
    assert all(0.0 <= i.parse_confidence <= 1.0 for i in incidents)
