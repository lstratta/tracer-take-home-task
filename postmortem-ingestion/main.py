#!/usr/bin/env python3
"""CLI entry point — Pillar 1 Incident Data Ingestion Application.

Wires together all pipeline components and exposes three commands:
  run         Full pipeline: crawl → parse → normalise → deduplicate → score → store
  crawl-only  Fetch raw content only, useful for debugging
  stats       Print summary statistics from the stored index
"""

import os
import sys
from collections import Counter
from datetime import datetime, timezone

import click
import yaml

from utils.logger import configure_logging, get_logger
from crawler.github_crawler import GitHubCrawler
from parser.markdown_parser import parse as parse_markdown
from parser.link_resolver import resolve as resolve_links
from normaliser.normaliser import normalise
from normaliser.deduplicator import deduplicate
from normaliser.quality_scorer import score
from storage.json_store import JsonStore

log = get_logger("main")


def _load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@click.group()
@click.option(
    "--config",
    default="config.yaml",
    show_default=True,
    help="Path to the YAML configuration file.",
)
@click.pass_context
def cli(ctx: click.Context, config: str) -> None:
    """Pillar 1 Incident Data Ingestion — crawls danluu/post-mortems into structured JSON."""
    configure_logging()
    ctx.ensure_object(dict)
    ctx.obj["config"] = _load_config(config)


@cli.command()
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

    # Stage 2b: optional link resolution
    raw_incidents = resolve_links(raw_incidents, config)

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

    # Stage 5: quality score
    log.info("Stage: quality_score", input_count=len(incident_records))
    for record in incident_records:
        try:
            score(record, config)
        except Exception as exc:
            msg = f"Quality scoring failed for {record.id}: {exc}"
            log.error("Quality scoring error", record_id=record.id, error=str(exc))
            errors.append(msg)

    # Stage 6: store
    log.info("Stage: store", input_count=len(incident_records))
    storage_result = store.save_all(incident_records, source_sha=crawl_result.sha)

    # Stage 7: update run state
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
    click.echo(f"  Records stored:       {storage_result['saved']}")
    click.echo(f"  Records skipped:      {storage_result['skipped']}")
    click.echo(f"  Errors:               {len(errors)}")
    if errors:
        click.echo("\nErrors:")
        for err in errors:
            click.echo(f"  - {err}")


@cli.command("crawl-only")
@click.pass_context
def crawl_only(ctx: click.Context) -> None:
    """Fetch and save raw README content without processing. Useful for debugging."""
    config = ctx.obj["config"]
    crawler = GitHubCrawler(config)
    target_file = config["parsing"]["target_file"]

    crawl_result = crawler.crawl(target_file)
    if crawl_result is None:
        click.echo("No content returned.")
        return

    os.makedirs("./output", exist_ok=True)
    output_path = "./output/raw_readme.md"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(crawl_result.content)

    click.echo(f"Raw content saved to {output_path}")
    click.echo(f"SHA: {crawl_result.sha}")
    click.echo(f"Content length: {len(crawl_result.content):,} characters")


@cli.command()
@click.pass_context
def stats(ctx: click.Context) -> None:
    """Print summary statistics from the output index."""
    config = ctx.obj["config"]
    store = JsonStore(config)
    index = store.load_index()
    records = index.get("records", [])

    if not records:
        click.echo("No records found in index.")
        return

    quality_scores = [r["quality_score"] for r in records if r.get("quality_score") is not None]
    low_quality_count = sum(1 for r in records if r.get("low_quality"))
    near_dup_count = sum(1 for r in records if r.get("potential_duplicate_of"))
    sections = Counter(r.get("section") for r in records if r.get("section"))
    companies = Counter(r.get("company") for r in records if r.get("company"))

    click.echo("\n=== Index Statistics ===")
    click.echo(f"  Last updated:        {index.get('last_updated', 'N/A')}")
    click.echo(f"  Source SHA:          {index.get('source_sha', 'N/A')}")
    click.echo(f"  Total records:       {len(records)}")
    click.echo(f"  Low quality:         {low_quality_count}")
    click.echo(f"  Near-duplicate flags:{near_dup_count}")

    if quality_scores:
        avg = sum(quality_scores) / len(quality_scores)
        click.echo(f"\n  Quality score distribution:")
        click.echo(f"    Min:      {min(quality_scores):.3f}")
        click.echo(f"    Max:      {max(quality_scores):.3f}")
        click.echo(f"    Average:  {avg:.3f}")
        buckets = {"0.0–0.3": 0, "0.3–0.6": 0, "0.6–0.8": 0, "0.8–1.0": 0}
        for s in quality_scores:
            if s < 0.3:
                buckets["0.0–0.3"] += 1
            elif s < 0.6:
                buckets["0.3–0.6"] += 1
            elif s < 0.8:
                buckets["0.6–0.8"] += 1
            else:
                buckets["0.8–1.0"] += 1
        for bucket, count in buckets.items():
            click.echo(f"    {bucket}: {count}")

    if sections:
        click.echo(f"\n  Top 10 sections:")
        for section, count in sections.most_common(10):
            click.echo(f"    {section}: {count}")

    if companies:
        click.echo(f"\n  Top 10 companies:")
        for company, count in companies.most_common(10):
            click.echo(f"    {company}: {count}")


if __name__ == "__main__":
    cli()
