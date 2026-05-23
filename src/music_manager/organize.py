import shutil
from pathlib import Path

from music_manager.track import Track


def _sanitize(component: str) -> str:
    """Strip leading/trailing whitespace, replace '/' with '-' and ':' with ' - '."""
    return component.strip().replace("/", "-").replace(":", " - ")


def destination_path(track: Track, library_root: Path) -> Path:
    """Compute the target path for a track within the library.

    Pattern: library_root / album_artist / album / "artist - title.m4a"
    """
    folder_artist = track.album_artist.strip() or track.artist.strip()
    artist = _sanitize(folder_artist) if folder_artist else "Unknown Artist"
    album_folder = _sanitize(track.album) if track.album.strip() else "Unknown Album"

    track_artist_raw = track.artist.strip() or folder_artist
    track_artist = _sanitize(track_artist_raw) if track_artist_raw else "Unknown Artist"

    if track.title.strip():
        title = _sanitize(track.title)
    else:
        title = track.path.stem

    filename = f"{track_artist} - {title}.m4a"
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
