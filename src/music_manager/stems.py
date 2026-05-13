from pathlib import Path

from mutagen.mp4 import MP4

from .organize import _sanitize


def _read_metadata(path: Path) -> dict:
    """Read MP4/M4A tags from *path*, returning title, album_artist, album, year."""
    try:
        tags = MP4(str(path)).tags or {}

        def _get(key: str, default: str = "") -> str:
            vals = tags.get(key)
            return str(vals[0]) if vals else default

        return {
            "title": _get("\xa9nam") or path.stem,
            "album_artist": _get("aART") or _get("\xa9ART"),
            "album": _get("\xa9alb"),
            "year": _get("\xa9day")[:4],
        }
    except Exception:
        return {"title": path.stem, "album_artist": "", "album": "", "year": ""}


def stem_output_dir(track_path: Path, output_root: Path) -> Path:
    """Compute the directory where stems for *track_path* will be written.

    Pattern: output_root/stems/album_artist/album (YEAR)/title/
    """
    meta = _read_metadata(track_path)

    artist = _sanitize(meta["album_artist"]) or "Unknown Artist"
    album = _sanitize(meta["album"]) or "Unknown Album"
    year = _sanitize(meta["year"])
    title = _sanitize(meta["title"]) or track_path.stem

    album_folder = f"{album} ({year})" if year else album

    return output_root / "stems" / artist / album_folder / title


def _run_demucs(track_path: Path, out_dir: Path) -> None:
    """Load the htdemucs model and write {vocals,drums,bass,other}.wav to *out_dir*."""
    import torch
    from demucs.pretrained import get_model
    from demucs.apply import apply_model
    from demucs.audio import AudioFile, save_audio

    model = get_model(name="htdemucs")
    model.eval()

    wav = AudioFile(track_path).read(
        streams=0,
        samplerate=model.samplerate,
        channels=model.audio_channels,
    )
    ref = wav.mean(0)
    wav = (wav - ref.mean()) / ref.std()

    with torch.no_grad():
        sources = apply_model(model, wav[None])[0]

    sources = sources * ref.std() + ref.mean()

    out_dir.mkdir(parents=True, exist_ok=True)
    for source, name in zip(sources, model.sources):
        save_audio(source, out_dir / f"{name}.wav", samplerate=model.samplerate)


def separate_stems(track_path: Path, output_root: Path, dry_run: bool = False) -> Path:
    """Separate *track_path* into stems using Demucs (htdemucs model).

    Writes {vocals,drums,bass,other}.wav under
        output_root / stems / album_artist / album (YEAR) / title /

    Returns the output directory path.
    Raises RuntimeError when demucs is not installed.
    """
    out_dir = stem_output_dir(track_path, output_root)

    if dry_run:
        return out_dir

    try:
        _run_demucs(track_path, out_dir)
    except ImportError as exc:
        raise RuntimeError(
            "demucs is not installed — run: uv sync --extra stems"
        ) from exc

    return out_dir
