"""Enrich command — run the LLM enricher on stored incidents."""

import click

from enricher.batch import run_batch
from storage.json_store import JsonStore
from utils.logger import get_logger

log = get_logger("enrich")


@click.command("enrich")
@click.option(
    "--count",
    default=10,
    show_default=True,
    help="Number of incidents to enrich. Ignored when --all is set.",
)
@click.option(
    "--all", "enrich_all",
    is_flag=True,
    default=False,
    help="Enrich all eligible incidents, not just --count.",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Re-enrich incidents that have already been enriched.",
)
@click.option(
    "--id", "incident_id",
    default=None,
    help="Enrich a single specific incident by its ID. Overrides --count and --all.",
)
@click.pass_context
def enrich_cmd(
    ctx: click.Context, count: int, enrich_all: bool, force: bool, incident_id: str
) -> None:
    """Run the LLM enricher on stored incidents that have not yet been enriched.

    Reads existing records from the index, fetches each source URL, calls the
    LLM to extract better structured data, re-scores quality, and writes the
    updated record back to disk.

    Examples:
      python main.py enrich --count 20
      python main.py enrich --all
      python main.py enrich --count 5 --force
      python main.py enrich --id ab3f7c2d
      python main.py enrich --id ab3f7c2d --force
    """
    config = ctx.obj["config"]
    store = JsonStore(config)

    # Guard: API key must be present before we do any work
    api_key = ctx.obj.get("anthropic_api_key")
    if not api_key or api_key == "your-api-key-here":
        click.echo(
            "ERROR: ANTHROPIC_API_KEY is not set in .env. "
            "Copy .env.example to .env and add your key."
        )
        return

    if not store.load_index().get("records"):
        click.echo("No records found in index. Run 'python main.py run' first.")
        return

    if incident_id:
        click.echo(f"\nEnriching incident {incident_id}...\n")
    else:
        click.echo(
            f"\nEnriching incidents "
            f"({'all eligible' if enrich_all else f'up to {count}'}, "
            f"{'including already-enriched' if force else 'unenriched only'})...\n"
        )

    # Delegate all record processing to the batch module
    result = run_batch(config, api_key, store, count, enrich_all, force, incident_id)

    # Print per-record status lines
    for r in result.record_results:
        click.echo(f"  {r.status.upper():<6}{r.record_id} — {r.reason}")

    click.echo(f"\n=== Enrichment Summary ===")
    click.echo(f"  Enriched: {result.enriched}")
    click.echo(f"  Skipped:  {result.skipped}")
    click.echo(f"  Errors:   {result.errors}")
