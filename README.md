# Postmortem Ingestion

Pillar 1 of the Failure Scenario Generation System. This application crawls the
[danluu/post-mortems](https://github.com/danluu/post-mortems) GitHub repository, parses and extracts structured 
incident data from its contents, normalises that data into a canonical schema, 
deduplicates it, scores it for quality, and persists it as JSON files for downstream 
consumption by classifier and scenario generation components.

## Contents

- [Where this fits](#where-this-fits)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [GitHub Token](#github-token)
- [Running the application](#running-the-application)
- [Output](#output)
  - [Individual record](#individual-record-ab3f7c2djson)
  - [Index](#index-outputindexjson)
  - [Run state](#run-state-outputrun_statejson)
- [Quality score](#quality-score)
- [Idempotency](#idempotency)
- [Package structure](#package-structure)
- [Running tests](#running-tests)
- [Compute estimates](#compute-estimates)
  - [run without enrichment](#run-without-enrichment)
  - [enrich](#enrich-the-expensive-stage)
  - [Scaling beyond the current source](#scaling-beyond-the-current-source)
  - [Bottlenecks at scale](#bottlenecks-at-scale)
- [Potential improvements](#potential-improvements)
- [Known limitations](#known-limitations)

## Prerequisites

- Python 3.10 or later
- pip
- make

## Installation

```bash
pip install -r requirements.txt

# using Nix flakes?
nix develop
```

## GitHub Token

Without a GitHub personal access token the API rate limit is **60 requests/hour**.
For normal usage, authenticated access at **5000 requests/hour** is recommended.

1. Create a token at <https://github.com/settings/tokens> (no scopes required for
   public repos)
2. Set the environment variable (or add them to .env):

```bash
export ANTHROPIC_API_KEY=your_api_key # required to run enrichment
export GITHUB_TOKEN=ghp_yourtoken
```

The application warns at startup if no token is configured.

## Running the application

```bash
make run
```

**Summary statistics** from the stored index:

```bash
make stats
```

**LLM enrichment** on stored incidents (requires `ANTHROPIC_API_KEY` in `.env`):

```bash
# Convenience commands
make enrich # defaults to 10
make enrich COUNT=15 # can be any number
make enrich-all

# These are the raw commands
# Enrich the next 10 unenriched incidents (default)
python main.py enrich

# Enrich a specific number
python main.py enrich --count 25

# Enrich every eligible incident
python main.py enrich --all

# Re-enrich incidents that have already been enriched
python main.py enrich --count 5 --force

# Enrich a single specific incident by ID
python main.py enrich --id ab3f7c2d

# Force re-enrich a specific incident
python main.py enrich --id ab3f7c2d --force
```

Enrichment fetches each incident's source URL, sends the page content to an LLM,
and updates the record with a richer summary, root causes, remediation actions,
severity, and duration. Quality scores are recalculated afterwards.

All commands accept `--config` to point at a non-default config file:

```bash
python main.py --config /path/to/config.yaml run
```

## Output

All output is written to the directory configured in `config.yaml` (default: `./output`).

```
output/
  incidents/
    ab/
      abc123de.json      # individual incident record
    cd/
      cd0012ff.json
  index.json             # summary index of all records
  run_state.json         # state from the most recent run
```

### Individual record (`abc123de.json`)

Each file is a fully serialised `IncidentRecord`. All fields are present even if
`null`. Example fields:

| Field | Description |
|---|---|
| `id` | Stable 8-char SHA-256 hash of the source URL (or raw text) |
| `title` | Company/service name, or first sentence of description |
| `description` | Cleaned description text |
| `source_url` | URL of the original incident report |
| `date` | ISO 8601 date if found, else `null` |
| `affected_services` | List of extracted service names |
| `root_causes_raw` | Sentences containing root-cause signal keywords |
| `remediation_actions_raw` | Sentences containing remediation signal keywords |
| `quality_score` | Float 0–1 (see below) |
| `low_quality` | `true` if quality_score < configured threshold |
| `potential_duplicate_of` | ID of a near-duplicate record, if found |
| `llm_enriched` | `true` once the LLM enricher has processed this record |
| `llm_summary` | LLM-written summary of the incident (set after enrichment) |
| `llm_enriched_at` | ISO 8601 timestamp of when enrichment ran |

### Index (`output/index.json`)

Contains a summary of all stored records for fast lookup without reading every file.

### Run state (`output/run_state.json`)

Tracks the previous run: start/end timestamps, record counts, source SHA, and any
errors. Used for change detection (if the source SHA is unchanged, the crawl is
skipped) and for resumption diagnostics.

## Quality score

Each record receives a `quality_score` between 0.0 and 1.0, computed as a weighted
average of four components:

| Component | Weight | What it measures |
|---|---|---|
| Completeness | 40% | Fraction of expected fields that are populated |
| Specificity | 30% | Presence of error codes, metric names, infrastructure terms |
| Description length | 20% | Proxy for level of detail (500+ chars = 1.0) |
| Source reliability | 10% | Whether source URL is a known high-quality domain |

Records below `quality.minimum_score_threshold` (default 0.3) are flagged with
`low_quality: true`. They are stored and indexed normally — downstream components
decide what to do with them.

## Idempotency

Running the pipeline multiple times against unchanged source data produces the same
output with no duplicates introduced. This is guaranteed by:

1. **Change detection** — the crawler compares the source file SHA with the value
   stored in `run_state.json`. If they match, the crawl is skipped entirely.
2. **Stable IDs** — the same incident always gets the same ID (hash of its source URL
   or raw text), so filenames never change across runs.
3. **Skip-on-existing** — the store checks the index before writing; if a record with
   the same ID, source URL, or content hash already exists and `overwrite_existing` is
   `false`, it is skipped.

## Package structure

```
main.py                  # CLI entry point — registers commands and loads config/.env
cli/
  run.py                 # `run` command — orchestrates the full pipeline
  stats.py               # `stats` command — prints index summary statistics
  enrich.py              # `enrich` command — CLI layer for the batch enricher
crawler/
  github_crawler.py      # Fetches the danluu README via the GitHub Contents API
  rate_limiter.py        # Checks GitHub rate-limit headers and sleeps when needed
parser/
  markdown_parser.py     # Parses the README line-by-line into RawIncident objects
normaliser/
  normaliser.py          # Converts RawIncident → IncidentRecord (cleaning, hashing)
  deduplicator.py        # Exact and near-duplicate detection via SHA-256 + SimHash
  quality_scorer.py      # Scores each record 0–1 across four weighted components
enricher/
  fetcher.py             # Fetches and strips HTML from a post-mortem source URL
  llm_enricher.py        # LangChain + Anthropic LLM extraction into structured fields
  batch.py               # Batch loop — loads, enriches, re-scores, and saves records
storage/
  json_store.py          # Atomic JSON persistence with git-style subdirectory layout
models/
  raw_incident.py        # Dataclass for parser output before normalisation
  incident_record.py     # Pydantic model — the canonical schema written to disk
utils/
  logger.py              # Configures structlog with JSON output
  hashing.py             # SHA-256 and SimHash helpers
```

## Running tests

```bash
pytest tests/
```

Tests never make real network requests. The GitHub crawler accepts an injectable
HTTP client, and tests use `tests/fixtures/sample_readme.md` as input.

## Compute estimates

All estimates assume the current danluu/post-mortems corpus (~150 parsed incidents) and
the default `claude-sonnet-4-6` model. LLM API costs use public list pricing
($3/MTok input, $15/MTok output).

### `run` without enrichment

| Resource | Estimate | Reasoning |
|---|---|---|
| Wall time | < 5 s | One GitHub API call + regex parsing of ~250 KB + in-memory dedup/scoring of ~150 records |
| Peak memory | ~90 MB | Python process baseline (~80 MB) + all 150 records in memory (~3 KB each = ~450 KB) |
| API cost | $0 | One GitHub API request; unauthenticated rate limit (60 req/hr) is sufficient |

### `enrich` (the expensive stage)

Of ~150 parsed entries, roughly 120 pass the skip filters (valid URL, parse confidence ≥ 0.3,
page fetchable). Each record requires one HTTP fetch and one LLM call.

| Resource | Estimate | Reasoning |
|---|---|---|
| Wall time | ~16 min | 120 records × 8 s average (2 s HTTP fetch + 6 s LLM response) — sequential, no concurrency |
| Peak memory | ~90 MB | One record enriched at a time; the process baseline dominates |
| Input tokens | ~280 K | 120 calls × ~2,330 tokens (80 system + 250 metadata/taxonomy + ~2,000 page content) |
| Output tokens | ~48 K | 120 calls × ~400 tokens of structured JSON |
| LLM cost | **~$1.50** | Input: $0.84 · Output: $0.72 |
| Storage | < 1 MB | 120 enriched records × ~4 KB JSON + index + run state |

The 8 s per-record average assumes pages respond within ~2 s. URLs that time out
(30 s default) will inflate wall time; dead links are skipped after the full timeout.

### Scaling beyond the current source

| Corpus size | Eligible records | Sequential enrich time | Enrich time (10 workers) | LLM cost |
|---|---|---|---|---|
| 150 (current) | ~120 | ~16 min | ~2 min | ~$1.50 |
| 1,500 (10×) | ~1,200 | ~2.5 hr | ~15 min | ~$15 |
| 15,000 (100×) | ~12,000 | ~27 hr | ~2.5 hr | ~$150 |
| 150,000 (1,000×) | ~120,000 | ~11 days | ~27 hr | ~$1,500 |

### Bottlenecks at scale

1. **Sequential enrichment** — the biggest lever. The current implementation processes
   one record at a time. A `ThreadPoolExecutor` with 10 workers would give ~10× speedup
   at near-zero additional cost; the only constraint is the Anthropic tier rate limit
   (50 RPM on tier 1 for Sonnet).

2. **JSON index as a single file** — every `update_record` call rewrites the whole file.
   Fine at the current size (<50 KB) but degrades past ~50K records (~7 MB, frequent
   rewrites). SQLite or a proper database would remove this ceiling.

3. **All records in memory during `run`** — the normaliser and deduplicator load every
   record into a Python list before storing. Negligible now, but at 100K+ records
   (~300 MB) chunked streaming would be needed.

4. **Dead-link timeouts** — at scale, many URLs will be unreachable. Reducing
   `request_timeout_seconds` from 30 s to 5–10 s, or pre-screening with a HEAD request,
   recovers substantial wall time across large corpora.

## Potential improvements

**Concurrent enrichment** — the enrichment stage processes records one at a time. Running
fetches and LLM calls in parallel would cut enrichment time by an order of magnitude with
no change to output quality or cost.

**Prompt caching** — the system prompt sent to the LLM is identical across every call.
Enabling provider-side caching would significantly reduce token costs for large enrichment
runs.

**Batch API** — for non-time-sensitive enrichment, Anthropic's asynchronous Batch API
processes requests at 50% of the standard per-token price, halving the cost of bulk runs.

**Storage backend** — the JSON index is a single file rewritten on every update. Replacing
it with SQLite would handle larger corpora with faster lookups and safer concurrent writes.

**Affected services extraction** — the heuristic that identifies impacted services misses
common infrastructure names written in lowercase. A pre-compiled vocabulary of well-known
service names would meaningfully improve recall.

**Near-duplicate detection at scale** — the current comparison is quadratic: every record
is checked against every other. Beyond tens of thousands of records, a band-based indexing
strategy would keep detection fast without sacrificing accuracy.

**Pipeline checkpointing** — if the process is killed mid-run, it restarts from scratch.
Saving progress after each stage would allow resumption from the last completed point
rather than re-processing records already handled.

**Config-driven tuning** — several values that affect output quality (quality score
weights, keyword lists, LLM output token limit) are hardcoded. Exposing them in
`config.yaml` would allow tuning without touching source code.

## Known limitations

- **Production Use**: This application is designed as a data ingestion prototype
  and would require meaningful adaptation before being suitable for a production
  environment. This includes hardened error handling, secret management, deployment
  configuration, monitoring, and scalability work as described in the improvements
  section above.

- **Local file storage**: Records are written as JSON files to the local filesystem.
  In a production setting this would be replaced with object storage, which provides durability, replication,
  access control, and the ability to share data across multiple services or deployments
  without coupling them to a single machine's disk.

- **Information fetching**: If the crawler fails to fetch the source URL for a record,
  it logs a warning and moves on. No retry is attempted and the failure is not surfaced
  beyond the run summary.

- **Near-duplicate detection**: SimHash is effective for near-identical text but may
  flag unrelated incidents that happen to use similar technical vocabulary. Near-
  duplicates are flagged but never automatically removed.
