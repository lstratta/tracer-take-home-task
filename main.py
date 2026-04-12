#!/usr/bin/env python3
"""CLI entry point — Pillar 1 Incident Data Ingestion Application.

Wires together all pipeline components and exposes three commands:
  run     Full pipeline: crawl → parse → normalise → deduplicate → score → store
  stats   Print summary statistics from the stored index
  enrich  Run the LLM enricher on stored incidents
"""

import os

import click
import yaml
from dotenv import load_dotenv

from utils.logger import configure_logging, get_logger
from cli.run import run
from cli.stats import stats
from cli.enrich import enrich_cmd

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
    # Load .env before anything else so all components can read env vars normally
    load_dotenv()
    configure_logging()
    ctx.ensure_object(dict)
    ctx.obj["config"] = _load_config(config)

    # Read the API key here once and store it on the context so every subcommand
    # can pass it to build_llm() without each one having to read the env itself
    ctx.obj["anthropic_api_key"] = os.environ.get("ANTHROPIC_API_KEY")


cli.add_command(run)
cli.add_command(stats)
cli.add_command(enrich_cmd)


if __name__ == "__main__":
    cli()
