import shutil
from pathlib import Path

from music_manager.track import Track


def _sanitize(component: str) -> str:
    """Strip leading/trailing whitespace and replace '/' with '-'."""
    return component.strip().replace("/", "-")


def destination_path(track: Track, library_root: Path) -> Path:
    """Compute the target path for a track within the library.

    Pattern: library_root / artist / "album (YEAR)" / "NN title.m4a"
    """
    artist = _sanitize(track.artist) if track.artist.strip() else "Unknown Artist"
    album = _sanitize(track.album) if track.album.strip() else "Unknown Album"
    year = _sanitize(track.year)

    if year:
        album_folder = f"{album} ({year})"
    else:
        album_folder = album

    if track.title.strip():
        title = _sanitize(track.title)
    else:
        title = track.path.stem

    if track.track_number:
        filename = f"{track.track_number:02d} {title}.m4a"
    else:
        filename = f"{title}.m4a"

    return library_root / artist / album_folder / filename


def move_track(track: Track, library_root: Path, dry_run: bool = False) -> Path:
    """Move track.path to its destination within library_root.

    Creates parent directories as needed. Updates track.path to the new
    location. Returns the destination path.
    In dry_run mode, skips the actual move but still returns the destination.
    """
    dest = destination_path(track, library_root)

    if not dry_run:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(track.path), str(dest))

    track.path = dest
    return dest


def delete_original_wav(wav_path: Path, dry_run: bool = False) -> None:
    """Delete the given WAV file. In dry_run mode, skip deletion."""
    if not dry_run:
        wav_path.unlink()
