"""Optional external link resolver.

Only active when follow_external_links is true in config. Off by default
because it significantly increases crawl time and fails on URLs that have
gone offline. Failures never block the rest of the pipeline.
"""

import re
from typing import List
from urllib.parse import urlparse

import requests

from models.raw_incident import RawIncident
from utils.logger import get_logger

log = get_logger("link_resolver")

MAX_EXTERNAL_CONTENT_CHARS = 5000


def _extract_text_from_html(html: str) -> str:
    """Extract readable plain text from HTML. Simple tag-stripping — no browser required."""
    html = re.sub(
        r"<(script|style)[^>]*>.*?</(script|style)>",
        "",
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:MAX_EXTERNAL_CONTENT_CHARS]


def _is_allowed_domain(url: str, allowed_domains: List[str]) -> bool:
    try:
        domain = urlparse(url).netloc.lower()
        return any(
            domain == d or domain.endswith("." + d) for d in allowed_domains
        )
    except Exception:
        return False


def resolve(
    incidents: List[RawIncident],
    config: dict,
    http_client=None,
) -> List[RawIncident]:
    """Optionally follow primary URLs to fetch additional source content.

    For each RawIncident with a primary_url that matches the allowed domain
    list, makes an HTTP GET and appends extracted text to external_content.
    Any failure (404, timeout, connection error) is logged and skipped.

    Args:
        incidents: List of RawIncident objects from the parser.
        config: Full application config dict.
        http_client: Injectable HTTP client for testing.

    Returns:
        The same list, with external_content populated where applicable.
    """
    crawling_config = config.get("crawling", {})

    if not crawling_config.get("follow_external_links", False):
        log.info("External link following disabled — skipping link resolution")
        return incidents

    allowed_domains = crawling_config.get("allowed_external_domains", [])
    timeout = crawling_config.get("request_timeout_seconds", 30)
    session = http_client or requests.Session()

    for incident in incidents:
        if not incident.primary_url:
            continue

        if not _is_allowed_domain(incident.primary_url, allowed_domains):
            log.debug(
                "URL not in allowed domains — skipping",
                url=incident.primary_url,
                allowed_domains=allowed_domains,
            )
            continue

        try:
            response = session.get(incident.primary_url, timeout=timeout)
            response.raise_for_status()

            if "text/html" in response.headers.get("Content-Type", ""):
                incident.external_content = _extract_text_from_html(response.text)
                log.debug(
                    "Resolved external content",
                    url=incident.primary_url,
                    content_length=len(incident.external_content),
                )
        except Exception as exc:
            log.warning(
                "Failed to resolve external URL — skipping",
                url=incident.primary_url,
                error=str(exc),
            )

    return incidents
