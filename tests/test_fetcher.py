"""Tests for enricher/fetcher.py."""

import pytest
from unittest.mock import MagicMock, patch

import requests

from enricher.fetcher import _extract_text_from_html, fetch_content


@pytest.fixture
def config():
    """Minimal config with short timeout and small max_content_chars."""
    return {"enrichment": {"request_timeout_seconds": 10, "max_content_chars": 100}}


# ---------------------------------------------------------------------------
# _extract_text_from_html
# ---------------------------------------------------------------------------


def test_extract_removes_script_blocks():
    """Script tags and their contents are stripped entirely."""
    html = "<p>Hello</p><script>alert('xss')</script><p>World</p>"
    result = _extract_text_from_html(html)
    assert "alert" not in result
    assert "Hello" in result
    assert "World" in result


def test_extract_removes_style_blocks():
    """Style tags and their contents are stripped entirely."""
    html = "<p>Text</p><style>body { color: red; }</style><p>More</p>"
    result = _extract_text_from_html(html)
    assert "color" not in result
    assert "Text" in result
    assert "More" in result


def test_extract_strips_remaining_tags_and_returns_readable_text():
    """HTML tags are removed and the readable text content is returned."""
    html = "<h1>Title</h1><p>Some <strong>bold</strong> text.</p>"
    result = _extract_text_from_html(html)
    assert "Title" in result
    assert "bold" in result
    assert "text." in result
    assert "<" not in result


# ---------------------------------------------------------------------------
# fetch_content
# ---------------------------------------------------------------------------


def test_fetch_content_returns_extracted_text_for_html(config):
    """HTML responses are processed through the HTML extractor."""
    with patch("enricher.fetcher.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Type": "text/html"}
        mock_resp.text = "<p>Hello world</p>"
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        result = fetch_content("http://example.com", config)

    assert result is not None
    assert "Hello world" in result
    assert "<" not in result


def test_fetch_content_returns_text_for_plain_text_response(config):
    """text/plain responses are returned as-is (stripped)."""
    with patch("enricher.fetcher.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Type": "text/plain"}
        mock_resp.text = "  plain text content  "
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        result = fetch_content("http://example.com/doc.txt", config)

    assert result == "plain text content"


def test_fetch_content_returns_none_for_unsupported_content_type(config):
    """Non-text content types (e.g. application/json) return None."""
    with patch("enricher.fetcher.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.text = '{"key": "value"}'
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        result = fetch_content("http://example.com/api", config)

    assert result is None


def test_fetch_content_returns_none_on_http_error(config):
    """An HTTPError from raise_for_status causes fetch_content to return None."""
    with patch("enricher.fetcher.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Type": "text/html"}
        mock_resp.raise_for_status.side_effect = requests.HTTPError("404 Not Found")
        mock_get.return_value = mock_resp

        result = fetch_content("http://example.com/missing", config)

    assert result is None


def test_fetch_content_truncates_to_max_content_chars(config):
    """Content longer than max_content_chars is truncated to that length."""
    long_text = "a" * 200  # exceeds max_content_chars=100 from fixture
    with patch("enricher.fetcher.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Type": "text/plain"}
        mock_resp.text = long_text
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        result = fetch_content("http://example.com/long", config)

    assert result is not None
    assert len(result) == 100


def test_fetch_content_returns_none_when_extracted_text_is_empty(config):
    """HTML that yields no visible text after extraction returns None."""
    with patch("enricher.fetcher.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Type": "text/html"}
        mock_resp.text = "<script>doSomething();</script>"
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        result = fetch_content("http://example.com/empty", config)

    assert result is None
