"""Full pipeline command: crawl → parse → normalise → deduplicate → score → store."""

from datetime import datetime, timezone

import click

from crawler.github_crawler import GitHubCrawler
from enricher.fetcher import fetch_content
from enricher.llm_enricher import build_llm, enrich
from normaliser.deduplicator import deduplicate
from normaliser.normaliser import normalise
from normaliser.quality_scorer import score
from parser.markdown_parser import parse as parse_markdown
from storage.json_store import JsonStore
from utils.logger import get_logger

log = get_logger("run")


@click.command()
@click.pass_context
def run(ctx: click.Context) -> None:
    """Run the full pipeline: crawl → parse → normalise → deduplicate → score → store."""
    config = ctx.obj["config"]
    store = JsonStore(config)

    started_at = datetime.now(tz=timezone.utc).isoformat()
    errors = []

    # Stage 0: load run state for change detection and resumption
    run_state = store.load_run_state()
    last_sha = run_state.get("last_run", {}).get("source_sha")
    log.info("Pipeline starting", last_source_sha=last_sha)

    # Stage 1: crawl
    log.info("Stage: crawl")
    crawler = GitHubCrawler(config)
    target_file = config["parsing"]["target_file"]
    crawl_result = crawler.crawl(target_file, last_sha=last_sha)

    if crawl_result is None:
        click.echo("Source file unchanged since last run. Nothing to do.")
        return

    # Stage 2: parse
    log.info("Stage: parse", content_length=len(crawl_result.content))
    raw_incidents = parse_markdown(crawl_result.content, config["parsing"])
    records_parsed = len(raw_incidents)
    log.info("Parse stage complete", records_parsed=records_parsed)

    # Stage 3: normalise
    log.info("Stage: normalise", input_count=records_parsed)
    incident_records = []
    failed_records = []

    for raw in raw_incidents:
        try:
            record = normalise(raw, crawl_result.sha, config)
            incident_records.append(record)
        except Exception as exc:
            msg = f"Normalisation failed at line {raw.line_number}: {exc}"
            log.error("Normalisation error", line_number=raw.line_number, error=str(exc))
            errors.append(msg)
            failed_records.append(raw)

    log.info(
        "Normalise stage complete",
        records_normalised=len(incident_records),
        records_failed=len(failed_records),
    )

    # Stage 4: deduplicate
    log.info("Stage: deduplicate", input_count=len(incident_records))
    dedup_result = deduplicate(incident_records, config)
    incident_records = dedup_result.records
    log.info(
        "Deduplicate stage complete",
        output_count=len(incident_records),
        exact_removed=dedup_result.exact_duplicates_removed,
        near_flagged=dedup_result.near_duplicates_flagged,
    )

    # Stage 5: LLM enrichment
    # Fetch each new record's source page and use the LLM to extract richer
    # structured data, replacing the heuristic-extracted fields with better values.
    # Quality scoring runs after this so the score reflects the enriched content.
    enrichment_config = config.get("enrichment", {})
    records_enriched = 0
    records_enrichment_skipped = 0

    api_key = ctx.obj.get("anthropic_api_key")
    enrichment_enabled = (
        enrichment_config.get("enabled", True)
        and api_key
        and api_key != "your-api-key-here"
    )

    if enrichment_config.get("enabled", True) and not enrichment_enabled:
        # Warn clearly rather than letting the API call fail mid-pipeline
        click.echo(
            "WARNING: ANTHROPIC_API_KEY is not set in .env — skipping enrichment stage. "
            "Copy .env.example to .env and add your key to enable enrichment."
        )
        log.warning("Enrichment skipped — ANTHROPIC_API_KEY not configured")

    if enrichment_enabled:
        # Build the LLM client once — reused across all records in this run
        llm = build_llm(config, api_key)
        min_confidence = enrichment_config.get("min_parse_confidence", 0.3)
        log.info("Stage: enrich", input_count=len(incident_records))

        for record in incident_records:
            # Skip records with no usable URL or below the confidence threshold
            if not record.source_url or not record.source_url.startswith("http"):
                records_enrichment_skipped += 1
                continue
            if record.parse_confidence < min_confidence:
                log.debug(
                    "Skipping enrichment — low parse confidence",
                    record_id=record.id,
                    parse_confidence=record.parse_confidence,
                )
                records_enrichment_skipped += 1
                continue

            # Fetch the full post-mortem page content for the LLM
            page_content = fetch_content(record.source_url, config)
            if not page_content:
                records_enrichment_skipped += 1
                continue

            try:
                enrich(record, page_content, llm, config)
                records_enriched += 1
            except Exception as exc:
                msg = f"Enrichment failed for {record.id}: {exc}"
                log.error("Enrichment error", record_id=record.id, error=str(exc))
                errors.append(msg)

        log.info(
            "Enrich stage complete",
            records_enriched=records_enriched,
            records_skipped=records_enrichment_skipped,
        )
    elif not enrichment_config.get("enabled", True):
        log.info("Enrichment disabled in config — skipping stage")

    # Stage 6: quality score
    log.info("Stage: quality_score", input_count=len(incident_records))
    for record in incident_records:
        try:
            score(record, config)
        except Exception as exc:
            msg = f"Quality scoring failed for {record.id}: {exc}"
            log.error("Quality scoring error", record_id=record.id, error=str(exc))
            errors.append(msg)

    # Stage 7: store
    log.info("Stage: store", input_count=len(incident_records))
    storage_result = store.save_all(incident_records, source_sha=crawl_result.sha)

    # Stage 8: update run state
    completed_at = datetime.now(tz=timezone.utc).isoformat()
    store.save_run_state(
        {
            "last_run": {
                "started_at": started_at,
                "completed_at": completed_at,
                "source_sha": crawl_result.sha,
                "records_crawled": records_parsed,
                "records_parsed": records_parsed,
                "records_normalised": len(incident_records) + len(failed_records),
                "records_stored": storage_result["saved"],
                "records_skipped_duplicate": (
                    storage_result["skipped"] + dedup_result.exact_duplicates_removed
                ),
                "records_enriched": records_enriched,
                "records_enrichment_skipped": records_enrichment_skipped,
                "records_failed": len(failed_records),
                "errors": errors,
            }
        }
    )

    # Summary
    click.echo("\n=== Pipeline Summary ===")
    click.echo(f"  Source SHA:           {crawl_result.sha}")
    click.echo(f"  Records parsed:       {records_parsed}")
    click.echo(f"  Records normalised:   {len(incident_records)}")
    click.echo(f"  Exact dupes removed:  {dedup_result.exact_duplicates_removed}")
    click.echo(f"  Near dupes flagged:   {dedup_result.near_duplicates_flagged}")
    click.echo(f"  Records enriched:     {records_enriched}")
    click.echo(f"  Enrichment skipped:   {records_enrichment_skipped}")
    click.echo(f"  Records stored:       {storage_result['saved']}")
    click.echo(f"  Records skipped:      {storage_result['skipped']}")
    click.echo(f"  Errors:               {len(errors)}")
    if errors:
        click.echo("\nErrors:")
        for err in errors:
            click.echo(f"  - {err}")
