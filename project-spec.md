# Specification: Pillar 1 Incident Data Ingestion Application


## Project Overview


This application implements Pillar 1 of the Failure Scenario Generation System. Its sole responsibility is to crawl the `github.com/danluu/post-mortems` repository, parse and extract structured incident data from its contents, normalise that data into a canonical schema, deduplicate it, and persist it as JSON files for downstream consumption by the classifier and scenario generation components.


The application must be runnable as a one-shot CLI process and also as a scheduled recurring job. It must be idempotent — running it twice against the same source data produces the same output with no duplicates introduced.


---


## Project Structure


```

postmortem-ingestion/

├── README.md

├── requirements.txt

├── config.yaml                    # all tuneable parameters live here, not in code

├── main.py                        # CLI entry point

│

├── crawler/

│   ├── __init__.py

│   ├── github_crawler.py          # fetches raw content from the danluu repo

│   └── rate_limiter.py            # handles GitHub API rate limiting

│

├── parser/

│   ├── __init__.py

│   ├── markdown_parser.py         # extracts raw incident records from markdown

│   └── link_resolver.py           # follows external links to source material

│

├── normaliser/

│   ├── __init__.py

│   ├── normaliser.py              # transforms parsed data into canonical schema

│   ├── deduplicator.py            # identifies and merges duplicate records

│   └── quality_scorer.py         # assigns a quality score to each record

│

├── storage/

│   ├── __init__.py

│   └── json_store.py              # writes and manages JSON output files

│

├── models/

│   ├── __init__.py

│   ├── raw_incident.py            # dataclass for pre-normalisation data

│   └── incident_record.py         # dataclass for the canonical schema

│

└── utils/

    ├── __init__.py

    ├── logger.py                  # structured logging setup

    └── hashing.py                 # content hashing utilities for dedup

```


---


## Dependency List


The following libraries should be used. Include these in `requirements.txt`:


- `requests` — HTTP calls to the GitHub API and external URLs

- `PyYAML` — loading configuration from `config.yaml`

- `python-slugify` — generating filesystem-safe identifiers from incident titles

- `pydantic` — data validation and schema enforcement for the canonical model

- `click` — CLI interface for `main.py`

- `structlog` — structured JSON logging (critical for a data pipeline — log every decision)

- `simhash` — near-duplicate detection during deduplication

- `tenacity` — retry logic with exponential backoff for HTTP calls

- `python-dateutil` — robust date parsing across heterogeneous date formats

- `tqdm` — progress bars for long-running crawl and parse operations


---


## Configuration File Specification (`config.yaml`)


All tuneable parameters must be defined here. No magic numbers in code.


```yaml

github:

  repo_owner: "danluu"

  repo_name: "post-mortems"

  branch: "master"

  api_base_url: "https://api.github.com"

  raw_base_url: "https://raw.githubusercontent.com"

  # Optional: set via environment variable GITHUB_TOKEN for higher rate limits

  # Unauthenticated: 60 requests/hour. Authenticated: 5000 requests/hour.

  token_env_var: "GITHUB_TOKEN"


crawling:

  request_timeout_seconds: 30

  max_retries: 3

  retry_backoff_seconds: 2

  # Whether to follow external links found in the markdown to fetch source material

  follow_external_links: false

  # If follow_external_links is true, limit to these domains to avoid crawling the internet

  allowed_external_domains:

    - "github.com"

    - "aws.amazon.com"


parsing:

  # The danluu repo is a single README.md — this is the file we target

  target_file: "README.md"

  # Minimum number of characters in a parsed description to be considered valid

  min_description_length: 50


normalisation:

  # Fields considered required for a record to pass quality threshold

  required_fields:

    - "title"

    - "source_url"

    - "description"

  # Simhash similarity threshold for near-duplicate detection (0-1, lower = stricter)

  dedup_similarity_threshold: 0.9


quality:

  # Records below this score are stored but flagged as low quality

  minimum_score_threshold: 0.3


storage:

  output_directory: "./output/incidents"

  # Index file tracks all stored records for fast lookup without reading all files

  index_file: "./output/index.json"

  # Run state file tracks crawl progress to support resumption

  run_state_file: "./output/run_state.json"

  # Whether to overwrite existing records or skip them on re-run

  overwrite_existing: false

```


---


## Component Specifications


---


### 1. Entry Point (`main.py`)


**Purpose**: CLI interface that wires all components together and runs the pipeline.


**Commands to expose via Click**:


- `run` — executes the full pipeline: crawl → parse → normalise → deduplicate → store

- `crawl-only` — fetches and saves raw content without processing, useful for debugging

- `stats` — reads the output index and prints summary statistics: total records, quality score distribution, records per company/category if available


**Pipeline execution order within `run`**:


1. Load configuration from `config.yaml`

2. Initialise structured logger

3. Load existing run state (for resumption if previous run was interrupted)

4. Initialise the GitHub crawler

5. Fetch raw content from the target file in the repo

6. Pass raw content to the markdown parser to produce a list of `RawIncident` objects

7. Pass each `RawIncident` through the normaliser to produce `IncidentRecord` objects

8. Pass the full list of `IncidentRecord` objects through the deduplicator

9. Pass each deduplicated record through the quality scorer

10. Pass all records to the JSON store for persistence

11. Update the run state file with completion timestamp and record counts

12. Print a summary to stdout


**Error handling**: The pipeline must not crash on a single bad record. Wrap per-record processing in try/except, log the error with full context (which record, which stage, what the error was), and continue. Collect all errors and report them in the final summary.


**Logging**: Log the start and end of each pipeline stage with record counts. This makes it easy to identify where records are being lost.


---


### 2. GitHub Crawler (`crawler/github_crawler.py`)


**Purpose**: Fetches the raw markdown content of the danluu post-mortems repository.


**Key behaviour**:


The danluu post-mortems repo is a single `README.md` file containing a large markdown document with hundreds of incident entries organised by company/category. The crawler's job is to fetch this file's content as a raw string.


The crawler should use the GitHub Contents API (`GET /repos/{owner}/{repo}/contents/{path}`) rather than fetching the raw URL directly. This returns metadata alongside content, including the file's `sha` hash which is used to detect whether the file has changed since the last crawl run.


**Change detection**: Before fetching the full file, compare the current file `sha` from the API response against the `sha` stored in the run state file from the previous run. If they match, the file has not changed and the crawl can be skipped. Log this decision explicitly. This prevents unnecessary reprocessing on unchanged data.


**Authentication**: Read the GitHub token from the environment variable specified in config. If no token is present, log a warning noting the reduced rate limit and proceed without authentication. All API calls must include the token in the `Authorization` header when present.


**Rate limiting** (`crawler/rate_limiter.py`): Inspect the `X-RateLimit-Remaining` and `X-RateLimit-Reset` headers on every GitHub API response. If `X-RateLimit-Remaining` drops below 10, pause execution until the reset timestamp. Log the pause with the expected resume time.


**Retry logic**: Use `tenacity` to wrap all HTTP calls with exponential backoff. Retry on HTTP 429, 500, 502, 503, 504. Do not retry on 401, 403, 404 — these indicate configuration errors that retrying will not fix. Raise a clear exception with a human-readable message for non-retryable errors.


**Output**: Returns a `CrawlResult` object containing:

- The raw file content as a string

- The file's `sha` hash

- The timestamp of the crawl

- The HTTP response status code

- The URL that was fetched


---


### 3. Markdown Parser (`parser/markdown_parser.py`)


**Purpose**: Transforms the raw README.md content into a list of structured `RawIncident` objects.


**Understanding the source data structure**:


The danluu README.md has a specific structure that the parser must understand. It is organised as a series of markdown sections, each containing bullet-point lists of incident entries. Each entry is typically formatted as:


```

* [Company Name](URL to incident report) incident description text. Date if available.

```


Some entries have multiple URLs. Some have no URL. Some span multiple lines. Some have additional context or commentary. The parser must handle all of these variations gracefully.


The file also contains section headers (using `##` markdown heading syntax) that indicate categories such as company names or incident types. These headers provide valuable context and should be extracted as a `section` field on each incident.


**Parsing strategy**:


Parse the document line by line. Maintain a state machine with two states: currently inside a section (have seen a `##` header) and currently reading an incident entry (have seen a `*` or `-` bullet point). Multi-line bullet points (lines that are continuations of the previous bullet, not starting with `*` or `-`) should be appended to the current incident's description buffer.


For each bullet point entry:

1. Extract all markdown links using regex: `\[([^\]]+)\]\(([^)]+)\)` — this gives link text and URL

2. Treat the first link's text as the company or service name

3. Treat the first link's URL as the primary source URL

4. Treat the remaining text (after removing markdown link syntax) as the description

5. Attempt to extract a date from the description text using `dateutil.parser.parse` with fuzzy matching — dates may appear in many formats

6. Collect any additional URLs found in the entry as secondary source URLs


**Output per entry — `RawIncident` fields**:

- `raw_text`: the original unmodified bullet point text, preserved exactly as found

- `section`: the most recent `##` heading seen before this entry

- `company_or_service`: extracted from the first link text

- `primary_url`: the first URL found in the entry

- `secondary_urls`: any additional URLs found in the entry

- `description_raw`: the entry text with markdown link syntax removed but otherwise unmodified

- `date_raw`: the raw date string as found in the text, before any parsing

- `date_parsed`: a Python `datetime` object if date extraction succeeded, else `None`

- `parse_confidence`: a float 0–1 indicating how confident the parser is in the extracted fields — lower if no URL found, lower if description is very short, lower if date extraction failed

- `line_number`: the line number in the source file where this entry started, for traceability


**Error handling**: If a line cannot be parsed at all, store it as a `RawIncident` with all fields set to `None` except `raw_text` and `line_number`, and set `parse_confidence` to 0.0. Never silently discard a line — it should always be possible to trace every line of the source file to either a `RawIncident` or an explicit skip decision in the logs.


---


### 4. Link Resolver (`parser/link_resolver.py`)


**Purpose**: Optionally follows the primary URL of each `RawIncident` to fetch additional content from the source incident report.


**This component is only active when `follow_external_links: true` in config**. It is off by default because it significantly increases crawl time and can fail on external URLs that have gone offline.


**Behaviour when active**:


For each `RawIncident` with a non-null `primary_url`, make an HTTP GET request to that URL. If the response is HTML, extract the page title and the main body text using basic HTML parsing (do not use a full browser — simple `requests` + text extraction is sufficient). Append the extracted text to the `RawIncident`'s description buffer under a clearly marked `external_content` field.


Only follow URLs matching the `allowed_external_domains` list in config. Log and skip any URL not in the allowed list.


Handle failures gracefully: a 404, timeout, or connection error on an external URL should be logged and skipped. It must not block the rest of the pipeline.


---


### 5. Normaliser (`normaliser/normaliser.py`)


**Purpose**: Transforms each `RawIncident` into a canonical `IncidentRecord` conforming to the shared schema.


**This is the most important component for downstream compatibility.** The `IncidentRecord` schema is the contract between the ingestion system and the classifier and scenario generation systems. It must be defined precisely and validated with Pydantic.


**Transformation logic**:


- `id`: generate using the content hashing utility (see below) — hash of `primary_url` if present, else hash of `raw_text`. This must be stable across runs — the same incident always gets the same ID.

- `source_url`: taken directly from `primary_url`. If null, set to the danluu repo URL with a fragment pointing to the section and line number.

- `source_type`: hardcode to `"POSTMORTEM"` for all records from this source.

- `title`: use `company_or_service` if available. If not, extract the first sentence of `description_raw` truncated to 100 characters.

- `description`: cleaned version of `description_raw` — strip extra whitespace, remove markdown formatting characters, normalise unicode to NFC form.

- `company`: the `company_or_service` field from the raw incident.

- `section`: the section heading from the raw incident, normalised to lowercase with underscores.

- `date`: the `date_parsed` field if available. Store as an ISO 8601 string. If not available, store `null` — do not guess.

- `affected_services`: attempt to extract service names from the description using simple heuristics — look for capitalised proper nouns that appear alongside words like "service", "system", "database", "API", "server". This will be imperfect and is expected to be. Store as a list of strings. Store an empty list if nothing is found.

- `root_causes_raw`: attempt to extract root cause signals from the description. Look for sentences containing keywords: "caused by", "due to", "root cause", "because", "resulted in", "triggered by". Store the matching sentences as a list of strings. This is raw extraction — the classifier will refine it.

- `remediation_actions_raw`: attempt to extract remediation signals. Look for sentences containing: "fixed by", "resolved by", "mitigated by", "rolled back", "restarted", "deployed", "patched". Store matching sentences as a list of strings.

- `duration_minutes`: look for duration expressions in the description — patterns like "X hours", "X minutes", "X days". Convert to minutes as an integer. Store `null` if not found.

- `severity_raw`: look for severity indicators — words like "outage", "degraded", "partial", "complete", "major", "minor". Store the matched word(s) as a string. Do not map to a severity scale at this stage — that is the classifier's job.

- `tags`: initially populated from the `section` field. Additional tags may be added by later pipeline stages.

- `source_sha`: the `sha` of the source file from the crawl result. Allows tracing any record back to the exact version of the source file it came from.

- `ingested_at`: ISO 8601 timestamp of when this record was created.

- `content_hash`: hash of the normalised content fields (title + description + source_url) used for deduplication.

- `quality_score`: initially `null`, populated by the quality scorer.

- `parse_confidence`: carried over from `RawIncident`.


**Validation**: Use Pydantic to validate every `IncidentRecord` before it leaves the normaliser. Any record that fails validation should be logged with the specific validation error and set aside in a `failed_records` list rather than silently dropped.


---


### 6. Deduplicator (`normaliser/deduplicator.py`)


**Purpose**: Identifies and removes duplicate `IncidentRecord` objects from the list before storage.


**Two types of duplication to handle**:


**Exact duplicates**: Two records with identical `content_hash` values. Keep the one with the higher `parse_confidence`. Log every exact duplicate found with both record IDs.


**Near-duplicate detection using SimHash**: SimHash is a locality-sensitive hash that produces similar hash values for similar text. Compute a SimHash of each record's `title + description` concatenated. Compare all pairs using Hamming distance — two records whose SimHash values differ by fewer than a configurable number of bits (derived from `dedup_similarity_threshold` in config) are considered near-duplicates.


For near-duplicates: do not automatically merge them. Instead, flag both records with a `potential_duplicate_of` field containing the other record's ID, and a `duplicate_confidence` float. Keep both records in storage but mark them. This is conservative — it is better to keep a potential duplicate than to incorrectly discard a distinct incident. Automatic merging can be introduced later once the system is validated.


**Cross-run deduplication**: When writing records to storage, check the existing index file for records with matching `content_hash` or `source_url`. If a match is found and `overwrite_existing` is `false` in config, skip the new record and log the skip. This ensures that re-running the pipeline does not create duplicate files.


**Output**: Returns a `DeduplicationResult` containing the deduplicated list of `IncidentRecord` objects, a count of exact duplicates removed, a count of near-duplicates flagged, and a list of all duplicate pairs found.


---


### 7. Quality Scorer (`normaliser/quality_scorer.py`)


**Purpose**: Assigns a `quality_score` float between 0.0 and 1.0 to each `IncidentRecord`.


**Scoring components** (each component produces a sub-score, final score is weighted average):


**Completeness score** (weight: 40%): How many of the expected fields are populated? Check: `title`, `description`, `source_url`, `date`, `affected_services` (non-empty), `root_causes_raw` (non-empty), `remediation_actions_raw` (non-empty), `duration_minutes`. Score is `fields_populated / total_fields_checked`.


**Specificity score** (weight: 30%): Does the description contain specific technical detail? Heuristics: presence of error codes (regex for patterns like `HTTP 5xx`, `OOMKilled`, `ETIMEDOUT`), presence of metric references ("latency", "error rate", "throughput", "p99"), presence of infrastructure terms ("database", "cache", "queue", "load balancer", "DNS", "certificate"), presence of specific service names. Score is `signals_found / max_expected_signals`, capped at 1.0.


**Description length score** (weight: 20%): A proxy for detail level. Score is `min(len(description) / 500, 1.0)` — a description of 500 characters or more scores 1.0.


**Source reliability score** (weight: 10%): Is the `source_url` a known high-quality domain? Maintain a small hardcoded list of high-reliability domains (e.g., `aws.amazon.com`, `cloud.google.com`, `github.com`, `engineering.*`). If `source_url` matches, score 1.0. If `source_url` is present but unknown domain, score 0.7. If `source_url` is null, score 0.0.


**Flag records** below `minimum_score_threshold` from config with a `low_quality: true` field. These records are still stored — they are not discarded — but downstream components know to treat them with lower confidence.


---


### 8. JSON Store (`storage/json_store.py`)


**Purpose**: Persists `IncidentRecord` objects as individual JSON files and maintains an index.


**File naming convention**: Each record is stored as a separate JSON file. The filename is `{id}.json` where `id` is the record's stable `id` field. This ensures filenames are stable across runs and that a record's file can be found directly from its ID without scanning the directory.


**Directory organisation**: Records are stored in subdirectories based on the first two characters of their ID (similar to how Git stores objects). This prevents any single directory from containing too many files as the corpus grows:


```

output/incidents/

  ab/

    ab3f7c2d.json

    ab91e4a1.json

  cd/

    cd0012ff.json

  ...

```


**Individual record file format**: Each JSON file contains the full serialised `IncidentRecord` with all fields. Use `indent=2` for human readability. Fields with `null` values should still be present in the JSON with null values — do not omit them. This ensures downstream consumers can rely on a consistent schema regardless of how complete the record is.


**Index file** (`output/index.json`): A single JSON file containing a summary of all stored records. This is updated every time a record is written. Format:


```json

{

  "last_updated": "ISO 8601 timestamp",

  "total_records": 847,

  "source_sha": "abc123",

  "records": [

    {

      "id": "ab3f7c2d",

      "title": "...",

      "company": "...",

      "section": "...",

      "date": "...",

      "quality_score": 0.72,

      "low_quality": false,

      "potential_duplicate_of": null,

      "file_path": "ab/ab3f7c2d.json"

    }

  ]

}

```


The index allows downstream components to query the corpus without loading every individual file.


**Run state file** (`output/run_state.json`): Tracks the state of the most recent and previous runs. Used for change detection and resumption. Format:


```json

{

  "last_run": {

    "started_at": "ISO 8601",

    "completed_at": "ISO 8601",

    "source_sha": "abc123 — the GitHub file SHA from last crawl",

    "records_crawled": 1000,

    "records_parsed": 950,

    "records_normalised": 940,

    "records_stored": 847,

    "records_skipped_duplicate": 93,

    "records_failed": 10,

    "errors": []

  }

}

```


**Atomic writes**: Write each JSON file to a temporary filename first, then rename it to the final filename. On all major operating systems, rename is atomic. This prevents a partially written file from being read by a downstream consumer if the process is interrupted mid-write.


---


### 9. Data Models


#### `RawIncident` (`models/raw_incident.py`)


A plain Python dataclass (not Pydantic) representing the output of the parser before normalisation. All fields are nullable — the parser may not be able to extract everything from every entry. This model has no validation by design; it represents raw extracted data in its most faithful form.


#### `IncidentRecord` (`models/incident_record.py`)


A Pydantic `BaseModel` representing the canonical normalised schema. This is the contract model. All fields must be explicitly typed. Optional fields use `Optional[type]` with a default of `None`. Lists default to empty lists, not `None`. Include field-level docstrings explaining what each field means and how it was populated. Include a Pydantic validator that rejects records where both `title` and `description` are null or empty.


---


### 10. Utilities


#### Logger (`utils/logger.py`)


Configure `structlog` to output structured JSON logs to stdout. Every log entry must include: timestamp, log level, component name (which module is logging), and a `record_id` field when processing a specific record. This makes it possible to grep all log lines related to a single record across all pipeline stages.


#### Hashing (`utils/hashing.py`)


Provide two functions:

- `content_hash(text: str) -> str`: returns a truncated SHA-256 hex digest (first 8 characters) of the input text after normalising whitespace and lowercasing. Used for stable ID generation.

- `compute_simhash(text: str) -> int`: returns a 64-bit SimHash integer of the input text after tokenising into words. Used for near-duplicate detection.


Both functions must be pure — same input always produces same output. No randomness, no timestamps, no external dependencies.


---


## Critical Considerations Not Explicitly Listed


### GitHub API Token


Without a GitHub personal access token, the API rate limit is 60 requests per hour. The application must print a clear warning at startup if no token is configured, explaining how to create one and set the environment variable. Include this in the README.


### The danluu Repo is a Single File


This is architecturally important. Unlike repos with many files, the entire dataset is one large markdown file. The parser is therefore doing most of the heavy lifting. The crawler is relatively simple. Document this explicitly in the code so future maintainers understand why the architecture is the way it is.


### Idempotency


Running the pipeline multiple times must produce the same output. This requires: stable ID generation (same incident always gets same ID), skip-on-existing logic in the store, change detection using the file SHA. Document idempotency as an explicit design goal in the README and test it.


### No External Database Dependency


The application must run with zero external infrastructure — no database, no message queue, no cloud storage. Everything writes to local disk. This makes it easy to run locally, in CI, or in a simple cron job. The JSON files and index are the database.


### README Requirements


The README must include:

- What the application does and where it fits in the larger system

- Prerequisites (Python version, how to install dependencies)

- How to set up the GitHub token environment variable

- How to run the application

- What the output looks like and where it is written

- How to interpret the quality score

- How to interpret the run state file

- Known limitations (date extraction accuracy, description extraction from complex entries)


### Testing


Include a `tests/` directory with:

- Unit tests for the markdown parser covering: standard entry format, entry with no URL, entry with multiple URLs, multi-line entry, section header parsing

- Unit tests for the deduplicator covering: exact duplicate detection, near-duplicate flagging, cross-run duplicate detection

- Unit tests for the quality scorer covering: high quality record, minimal record, missing required fields

- A fixture file `tests/fixtures/sample_readme.md` containing 20–30 representative lines from the danluu README format, used as test input without making real network calls

- All network calls must be mockable — the crawler should accept an injected HTTP client so tests never make real network requests
