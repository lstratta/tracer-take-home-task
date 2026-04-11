"""Batch enrichment pipeline for stored incidents.

Separates the enrichment logic from the CLI layer so main.py stays thin.
Called by the 'enrich' command with options already resolved.
"""

from dataclasses import dataclass, field
from typing import Dict, List

from enricher.fetcher import fetch_content
from enricher.llm_enricher import build_llm, enrich
from normaliser.quality_scorer import score
from storage.json_store import JsonStore
from utils.logger import get_logger

log = get_logger("batch_enricher")


@dataclass
class RecordResult:
    """Outcome of enriching a single record — used by the CLI to print per-record status."""

    record_id: str
    status: str          # "ok", "skip", or "error"
    reason: str          # human-readable detail shown next to the status


@dataclass
class BatchEnrichmentResult:
    """Aggregate result returned to the CLI after a batch enrichment run."""

    enriched: int = 0
    skipped: int = 0
    errors: int = 0
    record_results: List[RecordResult] = field(default_factory=list)


def run_batch(
    config: dict,
    api_key: str,
    store: JsonStore,
    count: int,
    enrich_all: bool,
    force: bool,
) -> BatchEnrichmentResult:
    """Fetch, enrich, re-score, and save a batch of stored incidents.

    Reads candidate records from the index, skips those that are already enriched
    (unless force=True), loads each full record from disk, fetches its source URL,
    calls the LLM enricher, re-scores quality, and writes the result back.

    Args:
        config: Full application config dict.
        api_key: Anthropic API key (loaded from .env by main.py).
        store: JsonStore instance used for reading and writing records.
        count: Maximum number of records to process (ignored when enrich_all=True).
        enrich_all: When True, process all eligible records regardless of count.
        force: When True, re-enrich records that already have llm_enriched=True.

    Returns:
        BatchEnrichmentResult with per-record statuses and aggregate counts.
    """
    result = BatchEnrichmentResult()
    enrichment_config = config.get("enrichment", {})
    min_confidence = enrichment_config.get("min_parse_confidence", 0.3)

    index = store.load_index()
    all_entries = index.get("records", [])

    # Filter index entries to those that still need enriching
    candidates = [
        e for e in all_entries
        if force or not e.get("llm_enriched", False)
    ]

    # Slice to the requested batch size unless --all was passed
    batch = candidates if enrich_all else candidates[:count]

    if not batch:
        return result

    # Build the LLM client once — reused for every record in the batch
    llm = build_llm(config, api_key)

    for entry in batch:
        record_id = entry["id"]

        # Load the full record from disk — the index only holds summary fields
        record = store.load_record(record_id)
        if record is None:
            result.skipped += 1
            result.record_results.append(
                RecordResult(record_id, "skip", "file not found on disk")
            )
            continue

        # Skip records with no fetchable URL
        if not record.source_url or not record.source_url.startswith("http"):
            result.skipped += 1
            result.record_results.append(
                RecordResult(record_id, "skip", "no valid source URL")
            )
            continue

        # Skip low-confidence records to avoid wasting API calls on unreliable data
        if record.parse_confidence < min_confidence:
            result.skipped += 1
            result.record_results.append(
                RecordResult(
                    record_id,
                    "skip",
                    f"parse confidence {record.parse_confidence:.2f} below threshold {min_confidence}",
                )
            )
            continue

        # Fetch the post-mortem page content for the LLM
        page_content = fetch_content(record.source_url, config)
        if not page_content:
            result.skipped += 1
            result.record_results.append(
                RecordResult(record_id, "skip", f"could not fetch {record.source_url}")
            )
            continue

        try:
            # Enrich the record, then re-score so quality reflects the new content
            enrich(record, page_content, llm, config)
            score(record, config)

            # Write the updated record back and refresh its index entry
            store.update_record(record, index)
            result.enriched += 1
            title_preview = (record.title or "(no title)")[:60]
            result.record_results.append(RecordResult(record_id, "ok", title_preview))

        except Exception as exc:
            log.error("Enrichment failed", record_id=record_id, error=str(exc))
            result.errors += 1
            result.record_results.append(RecordResult(record_id, "error", str(exc)))

    # Flush the index once after all records are processed rather than per-record
    store._save_index(index)

    log.info(
        "Batch enrichment complete",
        enriched=result.enriched,
        skipped=result.skipped,
        errors=result.errors,
    )

    return result
