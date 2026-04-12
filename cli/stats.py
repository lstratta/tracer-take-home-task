"""Stats command — print summary statistics from the stored index."""

from collections import Counter

import click

from storage.json_store import JsonStore
from utils.logger import get_logger

log = get_logger("stats")


@click.command()
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
    # Build a "category > subcategory > type" label for each enriched record
    taxonomy_labels = Counter(
        " > ".join(filter(None, [
            r.get("taxonomy_category"),
            r.get("taxonomy_subcategory"),
            r.get("taxonomy_type"),
        ]))
        for r in records
        if r.get("taxonomy_category")
    )
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

    if taxonomy_labels:
        click.echo(f"\n  Top 10 taxonomy classifications:")
        for label, count in taxonomy_labels.most_common(10):
            click.echo(f"    {label}: {count}")

    if companies:
        click.echo(f"\n  Top 10 companies:")
        for company, count in companies.most_common(10):
            click.echo(f"    {company}: {count}")
