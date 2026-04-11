# postmortem-ingestion

Pillar 1 of the Failure Scenario Generation System. This application crawls the
[danluu/post-mortems](https://github.com/danluu/post-mortems) GitHub repository, parses and extracts structured 
incident data from its contents, normalises that data into a canonical schema, 
deduplicates it, scores it for quality, and persists it as JSON files for downstream 
consumption by classifier and scenario generation components.

## Where this fits

```
postmortem-ingestion (this app)
        │
        └─► output/incidents/*.json  ──►  classifier  ──►  scenario generator
```

This application is **Pillar 1 only**. It produces structured `IncidentRecord` JSON
files and an `output/index.json` index. Downstream components read from there.

## Prerequisites

- Python 3.10 or later
- pip

## Installation

```bash
pip install -r requirements.txt
```

## GitHub Token

Without a GitHub personal access token the API rate limit is **60 requests/hour**.
For normal usage, authenticated access at **5000 requests/hour** is recommended.

1. Create a token at <https://github.com/settings/tokens> (no scopes required for
   public repos)
2. Set the environment variable:

```bash
export GITHUB_TOKEN=ghp_yourtoken
```

The application warns at startup if no token is configured.

## Running the application

**Full pipeline** (crawl → parse → normalise → deduplicate → score → store):

```bash
python main.py run
```

**Fetch raw content only** (useful for debugging the parser):

```bash
python main.py crawl-only
```

**Summary statistics** from the stored index:

```bash
python main.py stats
```

**LLM enrichment** on stored incidents (requires `ANTHROPIC_API_KEY` in `.env`):

```bash
# Enrich the next 10 unenriched incidents (default)
python main.py enrich

# Enrich a specific number
python main.py enrich --count 25

# Enrich every eligible incident
python main.py enrich --all

# Re-enrich incidents that have already been enriched
python main.py enrich --count 5 --force
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
      ab3f7c2d.json      # individual incident record
    cd/
      cd0012ff.json
  index.json             # summary index of all records
  run_state.json         # state from the most recent run
```

### Individual record (`ab3f7c2d.json`)

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

## Running tests

```bash
pytest tests/
```

Tests never make real network requests. The GitHub crawler accepts an injectable
HTTP client, and tests use `tests/fixtures/sample_readme.md` as input.

## Known limitations

- **Date extraction accuracy**: dates appear in many formats in the source data.
  The parser uses `dateutil` with fuzzy matching, which handles most formats but
  occasionally misparses ambiguous strings (e.g. "March" without a year). Dates
  that cannot be parsed are stored as `null` rather than guessed.
- **Description extraction from complex entries**: some entries in the danluu README
  contain nested bullet points, code blocks, or unconventional formatting. The parser
  handles the common cases but may produce imperfect descriptions for unusual entries.
- **Affected services extraction**: heuristic-based, using proximity to context words
  like "service" and "database". Will miss services not near those words and may
  produce false positives for capitalised words in other contexts.
- **Near-duplicate detection**: SimHash is effective for near-identical text but may
  flag unrelated incidents that happen to use similar technical vocabulary. Near-
  duplicates are flagged but never automatically removed.
