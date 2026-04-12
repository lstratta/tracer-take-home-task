"""Crawl-only command — fetch raw source content without processing."""

import os

import click

from crawler.github_crawler import GitHubCrawler
from utils.logger import get_logger

log = get_logger("crawl")


@click.command("crawl-only")
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
