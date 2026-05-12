import click
from pathlib import Path

from .convert import convert_directory


@click.group()
def cli():
    """Music library manager — convert, tag, and organize your rips."""


@cli.command()
@click.argument("input_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--dry-run", is_flag=True, help="Preview actions without writing anything.")
def process(input_dir: Path, dry_run: bool):
    """Convert, tag, and organize all WAV files in INPUT_DIR."""
    click.echo(f"Processing: {input_dir}" + (" (dry run)" if dry_run else ""))

    # Phase 1: convert
    pairs = convert_directory(input_dir, dry_run=dry_run)
    if not pairs:
        click.echo("No WAV files found.")
        return

    for src, dest in pairs:
        status = "would convert" if dry_run else "converted"
        click.echo(f"  {status}: {src.name} → {dest.name}")

    click.echo(f"\n{len(pairs)} file(s) {'would be ' if dry_run else ''}converted.")


@cli.command()
@click.argument("target", type=click.Path(exists=True, path_type=Path))
def stems(target: Path):
    """Generate stems for a track or directory of tracks. (Phase 5 — coming soon)"""
    click.echo("Stem generation not yet implemented.")
