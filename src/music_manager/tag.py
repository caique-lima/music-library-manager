import requests
from mutagen.mp4 import MP4, MP4Cover

from music_manager.track import Track

COVER_ART_URL = "https://coverartarchive.org/recording/{recording_id}/front"


def fetch_cover_art(musicbrainz_recording_id: str) -> bytes:
    """Fetch cover art from the MusicBrainz Cover Art Archive.

    Returns image bytes on success, b"" on failure.
    """
    url = COVER_ART_URL.format(recording_id=musicbrainz_recording_id)
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return response.content
        return b""
    except Exception:
        return b""


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
