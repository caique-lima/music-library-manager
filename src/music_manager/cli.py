import os
import click
from pathlib import Path

from .convert import convert_directory
from .identify import identify
from .tag import tag_track
from .organize import move_track, delete_original_wav


@click.group()
def cli():
    """Music library manager — convert, tag, and organize your rips."""


@cli.command()
@click.argument("input_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--dry-run", is_flag=True, help="Preview actions without writing anything.")
@click.option("--api-key", envvar="ACOUSTID_API_KEY", required=True,
              help="AcoustID API key. Can also be set via ACOUSTID_API_KEY env var.")
def process(input_dir: Path, dry_run: bool, api_key: str):
    """Convert, tag, and organize all WAV files in INPUT_DIR."""
    click.echo(f"Processing: {input_dir}" + (" (dry run)" if dry_run else ""))

    pairs = convert_directory(input_dir, dry_run=dry_run)
    if not pairs:
        click.echo("No WAV files found.")
        return

    ok = skipped = 0

    for src_wav, alac_path in pairs:
        click.echo(f"\n  {src_wav.name}")

        if dry_run:
            click.echo("    would convert → identify → tag → organize")
            ok += 1
            continue

        track = identify(alac_path, api_key)

        if not track.title:
            click.echo("    [!] no match found — file left untagged in place")
            skipped += 1
            continue

        click.echo(f"    identified: {track.artist} — {track.title} ({track.year})")

        tag_track(track)
        dest = move_track(track, library_root=input_dir)
        delete_original_wav(src_wav)

        click.echo(f"    → {dest.relative_to(input_dir)}")
        ok += 1

    if not dry_run:
        click.echo(f"\nDone: {ok} organized, {skipped} skipped.")


@cli.command()
@click.argument("target", type=click.Path(exists=True, path_type=Path))
def stems(target: Path):
    """Generate stems for a track or directory of tracks. (Phase 5 — coming soon)"""
    click.echo("Stem generation not yet implemented.")
