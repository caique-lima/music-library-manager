import click
import hashlib
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from queue import Queue
from threading import Lock  # used inside _ProgressDisplay

import acoustid
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.text import Text

from .convert import wav_to_alac
from .identify import identify
from .tag import tag_track, read_tags
from .organize import move_track, delete_original_wav


def _dedup_wavs(wavs: list[Path]) -> tuple[list[Path], list[Path]]:
    """Return (unique, duplicates). Keeps the first of each duplicate group (by sort order)."""
    seen: dict[str, Path] = {}
    unique: list[Path] = []
    dupes: list[Path] = []
    for wav in wavs:
        digest = hashlib.md5()
        with wav.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                digest.update(chunk)
        h = digest.hexdigest()
        if h in seen:
            dupes.append(wav)
        else:
            seen[h] = wav
            unique.append(wav)
    return unique, dupes


@dataclass
class _TrackResult:
    src: Path
    status: str          # "ok" | "skipped" | "error"
    dest: Path | None = None
    label: str = ""      # human-readable artist — title


_PHASE_STYLE = {
    "converting":   "cyan",
    "identifying":  "yellow",
    "tagging":      "magenta",
    "moving":       "blue",
    "idle":         "dim",
}


@dataclass
class _ProgressDisplay:
    """Owns the Rich Live display: overall progress, per-worker status, results log."""

    total: int
    n_workers: int
    _lock: Lock = field(default_factory=Lock, init=False)
    _phases: list[str] = field(init=False)       # slot → current phase
    _files: list[str] = field(init=False)        # slot → current filename
    _results: list[Text] = field(init=False)
    _progress: Progress = field(init=False)
    _overall_task: int = field(init=False)
    _live: Live = field(init=False)

    def __post_init__(self) -> None:
        self._phases = ["idle"] * self.n_workers
        self._files = [""] * self.n_workers
        self._results = []
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold]Overall[/bold]"),
            BarColumn(bar_width=36),
            MofNCompleteColumn(),
            transient=False,
        )
        self._overall_task = self._progress.add_task("overall", total=self.total)
        self._live = Live(self._render(), refresh_per_second=10, console=Console(stderr=False))

    def _render(self) -> Panel:
        worker_table = Table.grid(padding=(0, 2))
        for i, (phase, fname) in enumerate(zip(self._phases, self._files)):
            style = _PHASE_STYLE.get(phase, "")
            worker_table.add_row(
                Text(f"Worker {i + 1}", style="bold"),
                Text(phase, style=style),
                Text(fname, style="dim"),
            )

        log_lines = Group(*self._results[-12:])  # show last 12 results
        body = Group(self._progress, Text(""), worker_table, Text(""), log_lines)
        return Panel(body, title="[bold]Music Library Manager[/bold]", border_style="bright_black")

    def __enter__(self) -> "_ProgressDisplay":
        self._live.__enter__()
        return self

    def __exit__(self, *args) -> None:
        self._live.__exit__(*args)

    def phase_callback(self, slot: int) -> Callable[[str, str], None]:
        """Return a callback for a worker slot: (phase, filename) → updates display."""
        def _cb(phase: str, filename: str = "") -> None:
            with self._lock:
                self._phases[slot] = phase
                self._files[slot] = filename
                self._live.update(self._render())
        return _cb

    def record_result(self, result: "_TrackResult", input_dir: Path) -> None:
        with self._lock:
            if result.status == "ok":
                rel = result.dest.relative_to(input_dir)
                t = Text()
                t.append("  ✓  ", style="green bold")
                t.append(result.label)
                t.append(f"\n     → {rel}", style="dim")
            elif result.status == "skipped":
                t = Text()
                t.append("  –  ", style="yellow")
                t.append(f"{result.src.name}: {result.label}", style="dim")
            else:
                t = Text()
                t.append("  ✗  ", style="red bold")
                t.append(f"{result.src.name}: {result.label}", style="dim")
            self._results.append(t)
            self._progress.advance(self._overall_task)
            self._live.update(self._render())


def _process_track(
    src_wav: Path,
    api_key: str | None,
    library_root: Path,
    on_phase: Callable[[str, str], None] | None = None,
) -> _TrackResult:
    def _phase(p: str) -> None:
        if on_phase:
            on_phase(p, src_wav.name)

    _phase("converting")
    alac_path = src_wav.with_suffix(".m4a")
    wav_to_alac(src_wav, alac_path)

    if not alac_path.exists():
        return _TrackResult(src=src_wav, status="error", label="conversion failed — .m4a not produced")

    _phase("identifying")
    try:
        track = identify(alac_path, api_key)
    except (acoustid.WebServiceError, acoustid.FingerprintGenerationError) as exc:
        return _TrackResult(src=src_wav, status="error", label=str(exc))

    if not track.title:
        return _TrackResult(src=src_wav, status="skipped", label="no match found")

    _phase("tagging")
    tag_track(track)

    _phase("moving")
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
def process(input_dir: Path, dry_run: bool, api_key: str | None, workers: int):
    """Convert, tag, and organize all WAV files in INPUT_DIR."""
    wavs = sorted({p for p in input_dir.iterdir() if p.suffix.lower() == ".wav"})
    if not wavs:
        click.echo("No WAV files found.")
        return

    wavs, dupes = _dedup_wavs(wavs)
    for dup in dupes:
        if dry_run:
            click.echo(f"  duplicate (would remove): {dup.name}")
        else:
            dup.unlink()
            click.echo(f"  removed duplicate: {dup.name}")

    if not wavs:
        click.echo("No unique WAV files to process.")
        return

    if dry_run:
        click.echo(f"Processing {len(wavs)} file(s) with {workers} worker(s) (dry run)\n")
        for wav in wavs:
            click.echo(f"  would process: {wav.name}")
        return

    ok = skipped = errors = 0
    failed_dir = input_dir / "failed_conversion"

    slot_queue: Queue[int] = Queue()
    for i in range(workers):
        slot_queue.put(i)

    def _run_process(wav: Path) -> _TrackResult:
        slot = slot_queue.get()
        cb = display.phase_callback(slot)
        try:
            return _process_track(wav, api_key, input_dir, cb)
        finally:
            cb("idle", "")
            slot_queue.put(slot)

    with _ProgressDisplay(total=len(wavs), n_workers=workers) as display:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_run_process, wav): wav for wav in wavs}

            for future in as_completed(futures):
                result: _TrackResult = future.result()
                display.record_result(result, input_dir)

                if result.status == "ok":
                    ok += 1
                elif result.status == "skipped":
                    skipped += 1
                else:
                    failed_dir.mkdir(exist_ok=True)
                    dest = failed_dir / result.src.name
                    result.src.rename(dest)
                    errors += 1

    parts = [f"{ok} organized"]
    if skipped:
        parts.append(f"{skipped} skipped")
    if errors:
        parts.append(f"{errors} errors")
    click.echo(f"\nDone: {', '.join(parts)}.")


def _fix_track(
    m4a: Path,
    api_key: str | None,
    library_root: Path,
    on_phase: Callable[[str, str], None] | None = None,
) -> _TrackResult:
    def _phase(p: str) -> None:
        if on_phase:
            on_phase(p, m4a.name)

    track = read_tags(m4a)

    if not track.title or not track.artist or not track.cover_art:
        _phase("identifying")
        try:
            track = identify(m4a, api_key)
        except (acoustid.WebServiceError, acoustid.FingerprintGenerationError) as exc:
            return _TrackResult(src=m4a, status="error", label=str(exc))

        if not track.title:
            return _TrackResult(src=m4a, status="skipped", label="no match found")

        _phase("tagging")
        tag_track(track)

    _phase("moving")
    dest = move_track(track, library_root=library_root)
    label = f"{track.artist} — {track.title} ({track.year})"
    return _TrackResult(src=m4a, status="ok", dest=dest, label=label)


@cli.command()
@click.argument("input_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--api-key", envvar="ACOUSTID_API_KEY", default=None,
              help="AcoustID API key (or set ACOUSTID_API_KEY).")
@click.option("--workers", default=4, show_default=True,
              help="Number of tracks to process concurrently.")
def fix(input_dir: Path, api_key: str | None, workers: int):
    """Re-identify and re-tag existing .m4a files in INPUT_DIR (recursive)."""
    excluded = {input_dir / "stems"}
    m4as = sorted(
        p for p in input_dir.rglob("*.m4a")
        if not any(p.is_relative_to(ex) for ex in excluded)
    )
    if not m4as:
        click.echo("No .m4a files found.")
        return

    ok = skipped = errors = 0

    slot_queue: Queue[int] = Queue()
    for i in range(workers):
        slot_queue.put(i)

    def _run_fix(m4a: Path) -> _TrackResult:
        slot = slot_queue.get()
        cb = display.phase_callback(slot)
        try:
            return _fix_track(m4a, api_key, input_dir, cb)
        finally:
            cb("idle", "")
            slot_queue.put(slot)

    with _ProgressDisplay(total=len(m4as), n_workers=workers) as display:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_run_fix, m4a): m4a for m4a in m4as}

            for future in as_completed(futures):
                result: _TrackResult = future.result()
                display.record_result(result, input_dir)

                if result.status == "ok":
                    ok += 1
                elif result.status == "skipped":
                    skipped += 1
                else:
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
