"""GitHub crawler for the danluu/post-mortems repository.

Architecture note: the danluu post-mortems repo is a single README.md file
containing the entire dataset. Unlike repos with many files, the crawler's
job is simply to fetch that one file. The parser does the heavy lifting.
The GitHub Contents API is used (rather than the raw URL) because it returns
the file's SHA hash, which enables change detection — if the SHA matches the
previous run, there is no need to re-process unchanged data.
"""

import base64
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import requests
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from crawler.rate_limiter import check_and_wait_if_needed
from utils.logger import get_logger

log = get_logger("github_crawler")

NON_RETRYABLE_STATUS_CODES = {401, 403, 404}
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


@dataclass
class CrawlResult:
    """Result of a successful file crawl."""

    content: str
    sha: str
    crawled_at: str
    status_code: int
    url: str


class GitHubCrawler:
    """Fetches raw content from the danluu post-mortems GitHub repository."""

    def __init__(self, config: dict, http_client=None):
        self.config = config
        self.github_config = config["github"]
        self.crawling_config = config["crawling"]
        self._session = http_client or requests.Session()
        self._session.headers.update({"Accept": "application/vnd.github.v3+json"})
        self._setup_auth()

    def _setup_auth(self) -> None:
        token_env_var = self.github_config.get("token_env_var", "GITHUB_TOKEN")
        token = os.environ.get(token_env_var)
        if token:
            self._session.headers.update({"Authorization": f"token {token}"})
            log.info("GitHub token configured", env_var=token_env_var)
        else:
            log.warning(
                "No GitHub token found. Rate limit is 60 requests/hour. "
                "To increase to 5000/hour, create a personal access token at "
                "https://github.com/settings/tokens and set the environment variable.",
                env_var=token_env_var,
            )

    def _is_retryable(self, exc: Exception) -> bool:
        if isinstance(exc, requests.HTTPError):
            return exc.response.status_code in RETRYABLE_STATUS_CODES
        return isinstance(exc, (requests.ConnectionError, requests.Timeout))

    def _get(self, url: str) -> requests.Response:
        """GET request with retry logic, rate limit handling, and clear error messages."""

        @retry(
            stop=stop_after_attempt(self.crawling_config.get("max_retries", 3)),
            wait=wait_exponential(
                multiplier=self.crawling_config.get("retry_backoff_seconds", 2),
                min=1,
                max=60,
            ),
            retry=retry_if_exception(self._is_retryable),
            reraise=True,
        )
        def _do_get() -> requests.Response:
            response = self._session.get(
                url,
                timeout=self.crawling_config.get("request_timeout_seconds", 30),
            )
            check_and_wait_if_needed(response.headers)

            if response.status_code in NON_RETRYABLE_STATUS_CODES:
                raise requests.HTTPError(
                    f"Non-retryable HTTP {response.status_code} for {url}. "
                    "Check your GITHUB_TOKEN and repository configuration.",
                    response=response,
                )
            response.raise_for_status()
            return response

        return _do_get()

    def _contents_url(self, path: str) -> str:
        owner = self.github_config["repo_owner"]
        repo = self.github_config["repo_name"]
        branch = self.github_config.get("branch", "master")
        api_base = self.github_config["api_base_url"]
        return f"{api_base}/repos/{owner}/{repo}/contents/{path}?ref={branch}"

    def crawl(self, path: str, last_sha: Optional[str] = None) -> Optional[CrawlResult]:
        """Fetch a file from the repository.

        Compares the current file SHA against last_sha from the previous run.
        If they match, the file is unchanged and None is returned — no reprocessing needed.

        Args:
            path: File path within the repository (e.g. "README.md").
            last_sha: SHA stored from the previous crawl run, used for change detection.

        Returns:
            CrawlResult if the file was fetched, None if unchanged since last crawl.
        """
        url = self._contents_url(path)
        log.info("Fetching file from GitHub API", url=url, path=path)

        response = self._get(url)
        data = response.json()
        current_sha = data.get("sha")

        if last_sha and current_sha == last_sha:
            log.info(
                "File SHA unchanged since last crawl — skipping",
                path=path,
                sha=current_sha,
            )
            return None

        content_b64 = data.get("content", "")
        content = base64.b64decode(content_b64).decode("utf-8")

        log.info(
            "Successfully crawled file",
            path=path,
            sha=current_sha,
            content_length=len(content),
        )

        return CrawlResult(
            content=content,
            sha=current_sha,
            crawled_at=datetime.now(tz=timezone.utc).isoformat(),
            status_code=response.status_code,
            url=url,
        )
