import click
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import acoustid

from .convert import wav_to_alac
from .identify import identify
from .tag import tag_track, read_tags
from .organize import move_track, delete_original_wav


@dataclass
class _TrackResult:
    src: Path
    status: str          # "ok" | "skipped" | "error"
    dest: Path | None = None
    label: str = ""      # human-readable artist — title


def _process_track(src_wav: Path, api_key: str | None, library_root: Path, use_shazam: bool = False) -> _TrackResult:
    alac_path = src_wav.with_suffix(".m4a")
    wav_to_alac(src_wav, alac_path)

    if not alac_path.exists():
        return _TrackResult(src=src_wav, status="error", label="conversion failed — .m4a not produced")

    try:
        track = identify(alac_path, api_key, use_shazam=use_shazam)
    except acoustid.WebServiceError as exc:
        return _TrackResult(src=src_wav, status="error", label=str(exc))

    if not track.title:
        return _TrackResult(src=src_wav, status="skipped", label="no match found")

    tag_track(track)
    dest = move_track(track, library_root=library_root)
    delete_original_wav(src_wav)

    label = f"{track.artist} — {track.title} ({track.year})"
    return _TrackResult(src=src_wav, status="ok", dest=dest, label=label)


@click.group()
def cli():
    """Music library manager — convert, tag, and organize your rips."""


@cli.command()
@click.argument("input_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--dry-run", is_flag=True, help="Preview actions without writing anything.")
@click.option("--api-key", envvar="ACOUSTID_API_KEY", default=None,
              help="AcoustID API key (or set ACOUSTID_API_KEY).")
@click.option("--workers", default=4, show_default=True,
              help="Number of tracks to process concurrently.")
@click.option("--shazam", is_flag=True,
              help="Fall back to Shazam when AcoustID finds no match (slower — extracts audio).")
def process(input_dir: Path, dry_run: bool, api_key: str | None, workers: int, shazam: bool):
    """Convert, tag, and organize all WAV files in INPUT_DIR."""
    wavs = sorted({p for p in input_dir.iterdir() if p.suffix.lower() == ".wav"})
    if not wavs:
        click.echo("No WAV files found.")
        return

    click.echo(f"Processing {len(wavs)} file(s) with {workers} worker(s)"
               + (" (dry run)" if dry_run else "") + "\n")

    if dry_run:
        for wav in wavs:
            click.echo(f"  would process: {wav.name}")
        return

    ok = skipped = errors = 0

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_process_track, wav, api_key, input_dir, shazam): wav
            for wav in wavs
        }
        failed_dir = input_dir / "failed_conversion"

        for future in as_completed(futures):
            result: _TrackResult = future.result()
            if result.status == "ok":
                rel = result.dest.relative_to(input_dir)
                click.echo(f"  ✓  {result.label}\n     → {rel}")
                ok += 1
            elif result.status == "skipped":
                click.echo(f"  –  {result.src.name}: {result.label}")
                skipped += 1
            else:
                failed_dir.mkdir(exist_ok=True)
                dest = failed_dir / result.src.name
                result.src.rename(dest)
                click.echo(f"  ✗  {result.src.name}: {result.label}\n     → failed_conversion/")
                errors += 1

    parts = [f"{ok} organized"]
    if skipped:
        parts.append(f"{skipped} skipped")
    if errors:
        parts.append(f"{errors} errors")
    click.echo(f"\nDone: {', '.join(parts)}.")


def _fix_track(m4a: Path, api_key: str | None, library_root: Path, use_shazam: bool = False) -> _TrackResult:
    track = read_tags(m4a)

    if not track.title or not track.artist:
        # Tags incomplete — re-identify
        try:
            track = identify(m4a, api_key, use_shazam=use_shazam)
        except acoustid.WebServiceError as exc:
            return _TrackResult(src=m4a, status="error", label=str(exc))

        if not track.title:
            return _TrackResult(src=m4a, status="skipped", label="no match found")

        tag_track(track)

    dest = move_track(track, library_root=library_root)
    label = f"{track.artist} — {track.title} ({track.year})"
    return _TrackResult(src=m4a, status="ok", dest=dest, label=label)


@cli.command()
@click.argument("input_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--api-key", envvar="ACOUSTID_API_KEY", default=None,
              help="AcoustID API key (or set ACOUSTID_API_KEY).")
@click.option("--workers", default=4, show_default=True,
              help="Number of tracks to process concurrently.")
@click.option("--shazam", is_flag=True,
              help="Fall back to Shazam when AcoustID finds no match (slower — extracts audio).")
def fix(input_dir: Path, api_key: str | None, workers: int, shazam: bool):
    """Re-identify and re-tag existing .m4a files in INPUT_DIR (recursive)."""
    excluded = {input_dir / "stems"}
    m4as = sorted(
        p for p in input_dir.rglob("*.m4a")
        if not any(p.is_relative_to(ex) for ex in excluded)
    )
    if not m4as:
        click.echo("No .m4a files found.")
        return

    click.echo(f"Fixing {len(m4as)} file(s) with {workers} worker(s)\n")

    ok = skipped = errors = 0

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_fix_track, m4a, api_key, input_dir, shazam): m4a
            for m4a in m4as
        }
        for future in as_completed(futures):
            result: _TrackResult = future.result()
            if result.status == "ok":
                rel = result.dest.relative_to(input_dir)
                click.echo(f"  ✓  {result.label}\n     → {rel}")
                ok += 1
            elif result.status == "skipped":
                click.echo(f"  –  {result.src.name}: {result.label}")
                skipped += 1
            else:
                click.echo(f"  ✗  {result.src.name}: {result.label}")
                errors += 1

    parts = [f"{ok} fixed"]
    if skipped:
        parts.append(f"{skipped} skipped")
    if errors:
        parts.append(f"{errors} errors")
    click.echo(f"\nDone: {', '.join(parts)}.")


@cli.command()
@click.argument("target", type=click.Path(exists=True, path_type=Path))
@click.option("--dry-run", is_flag=True, help="Preview output paths without separating.")
def stems(target: Path, dry_run: bool):
    """Separate vocals, drums, bass, and other stems for TARGET (file or directory)."""
    from .stems import separate_stems

    if target.is_file():
        files = [target]
        output_root = target.parent
    else:
        files = sorted(p for p in target.rglob("*.m4a"))
        if not files:
            click.echo("No M4A files found.")
            return
        output_root = target

    click.echo(
        f"Separating stems for {len(files)} file(s)"
        + (" (dry run)" if dry_run else "")
        + "\n"
    )

    ok = errors = 0
    for track_path in files:
        try:
            out_dir = separate_stems(track_path, output_root, dry_run=dry_run)
            click.echo(f"  ✓  {track_path.name}\n     → {out_dir}")
            ok += 1
        except RuntimeError as exc:
            click.echo(f"  ✗  {track_path.name}: {exc}")
            errors += 1

    parts = [f"{ok} separated"]
    if errors:
        parts.append(f"{errors} errors")
    click.echo(f"\nDone: {', '.join(parts)}.")
