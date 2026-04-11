import time
from datetime import datetime, timezone
from typing import Mapping

from utils.logger import get_logger

log = get_logger("rate_limiter")

LOW_RATE_LIMIT_THRESHOLD = 10


def check_and_wait_if_needed(response_headers: Mapping[str, str]) -> None:
    """Inspect GitHub API rate limit headers and pause if remaining requests are low.

    Reads X-RateLimit-Remaining and X-RateLimit-Reset from the response headers.
    If remaining drops below LOW_RATE_LIMIT_THRESHOLD, execution is paused until
    the reset timestamp. Every pause is logged with the expected resume time.

    Args:
        response_headers: HTTP response headers from a GitHub API call.
    """
    remaining_raw = response_headers.get("X-RateLimit-Remaining")
    reset_raw = response_headers.get("X-RateLimit-Reset")

    if remaining_raw is None or reset_raw is None:
        return

    remaining = int(remaining_raw)
    reset_timestamp = int(reset_raw)

    if remaining < LOW_RATE_LIMIT_THRESHOLD:
        now = time.time()
        wait_seconds = max(0, reset_timestamp - now) + 1  # +1s buffer
        resume_time = datetime.fromtimestamp(reset_timestamp, tz=timezone.utc).isoformat()

        log.warning(
            "GitHub API rate limit low — pausing execution",
            remaining=remaining,
            reset_at=resume_time,
            wait_seconds=round(wait_seconds, 1),
        )
        time.sleep(wait_seconds)
        log.info("Resuming after rate limit pause")
