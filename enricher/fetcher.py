"""Fetches the full text content of a post-mortem URL for LLM enrichment."""

import re
from typing import Optional

import requests

from utils.logger import get_logger

log = get_logger("fetcher")

DEFAULT_MAX_CONTENT_CHARS = 50_000
DEFAULT_TIMEOUT_SECONDS = 30


def _extract_text_from_html(html: str) -> str:
    """Strip HTML tags and return readable plain text."""
    # Remove script and style blocks entirely
    html = re.sub(
        r"<(script|style)[^>]*>.*?</(script|style)>",
        "",
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    # Replace block-level tags with newlines to preserve some structure
    html = re.sub(r"<(br|p|div|h[1-6]|li|tr)[^>]*>", "\n", html, flags=re.IGNORECASE)
    # Strip remaining tags
    text = re.sub(r"<[^>]+>", " ", html)
    # Collapse whitespace while preserving paragraph breaks
    text = re.sub(r" +", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def fetch_content(url: str, config: dict) -> Optional[str]:
    """Fetch the readable text content of a URL.

    Returns plain text truncated to max_content_chars, or None on any failure.
    Failures are logged as warnings — the caller decides whether to skip enrichment.

    Args:
        url: The post-mortem URL to fetch.
        config: Full application config dict.

    Returns:
        Plain text string, or None if the fetch failed or content is unusable.
    """
    enrichment_config = config.get("enrichment", {})
    timeout = enrichment_config.get("request_timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    max_chars = enrichment_config.get("max_content_chars", DEFAULT_MAX_CONTENT_CHARS)

    try:
        response = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": "postmortem-ingestion/1.0"},
        )
        response.raise_for_status()
    except Exception as exc:
        log.warning("Failed to fetch URL for enrichment", url=url, error=str(exc))
        return None

    content_type = response.headers.get("Content-Type", "")

    if "text/html" in content_type:
        text = _extract_text_from_html(response.text)
    elif "text/" in content_type:
        text = response.text.strip()
    else:
        log.warning(
            "Unsupported content type — skipping enrichment",
            url=url,
            content_type=content_type,
        )
        return None

    if not text:
        log.warning("Empty content after extraction", url=url)
        return None

    if len(text) > max_chars:
        log.debug(
            "Content truncated for LLM",
            url=url,
            original_chars=len(text),
            truncated_to=max_chars,
        )

    return text[:max_chars]
