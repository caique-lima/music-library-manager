from pathlib import Path

from mutagen.mp4 import MP4, MP4Cover

from music_manager.cache import fetch_url
from music_manager.track import Track

COVER_ART_URL = "https://coverartarchive.org/recording/{recording_id}/front"


def read_tags(path: Path) -> Track:
    """Read existing MP4 tags from a file into a Track."""
    audio = MP4(str(path))
    return Track(
        path=path,
        title=audio.get("\xa9nam", [""])[0],
        artist=audio.get("\xa9ART", [""])[0],
        album=audio.get("\xa9alb", [""])[0],
        year=str(audio.get("\xa9day", [""])[0])[:4],
        genre=audio.get("\xa9gen", [""])[0],
        track_number=audio.get("trkn", [(0, 0)])[0][0],
    )


def fetch_cover_art(musicbrainz_recording_id: str) -> bytes:
    return fetch_url(COVER_ART_URL.format(recording_id=musicbrainz_recording_id))


def write_tags(track: Track) -> None:
    """Write MP4 metadata tags to the file at track.path."""
    audio = MP4(str(track.path))

    if track.title:
        audio["\xa9nam"] = [track.title]
    if track.artist:
        audio["\xa9ART"] = [track.artist]
    if track.album:
        audio["\xa9alb"] = [track.album]
    if track.year:
        audio["\xa9day"] = [track.year]
    if track.genre:
        audio["\xa9gen"] = [track.genre]
    if track.track_number:
        audio["trkn"] = [(track.track_number, 0)]
    if track.cover_art:
        audio["covr"] = [MP4Cover(track.cover_art, imageformat=MP4Cover.FORMAT_JPEG)]

    audio.save()


def tag_track(track: Track) -> None:
    """Orchestrate cover art fetching and tag writing for a track."""
    if track.musicbrainz_recording_id and not track.cover_art:
        track.cover_art = fetch_cover_art(track.musicbrainz_recording_id)
    write_tags(track)
