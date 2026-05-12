import ffmpeg
from pathlib import Path


def wav_to_alac(src: Path, dest: Path) -> Path:
    """Convert a WAV file to ALAC (.m4a). Returns the output path."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    (
        ffmpeg
        .input(str(src))
        .output(str(dest), acodec="alac", loglevel="error")
        .overwrite_output()
        .run()
    )
    return dest


def convert_directory(input_dir: Path, dry_run: bool = False) -> list[tuple[Path, Path]]:
    """
    Find all WAV files in input_dir (non-recursive) and convert each to ALAC
    in the same directory. Returns list of (src, dest) pairs.
    """
    wavs = sorted(input_dir.glob("*.wav"))
    if not wavs:
        return []

    pairs = [(wav, wav.with_suffix(".m4a")) for wav in wavs]

    if not dry_run:
        for src, dest in pairs:
            wav_to_alac(src, dest)

    return pairs
