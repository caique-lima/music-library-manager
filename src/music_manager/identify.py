import time
from pathlib import Path

import acoustid
import musicbrainzngs

from music_manager.track import Track

_USER_AGENT_APP = "music-manager"
_USER_AGENT_VERSION = "0.1"
_USER_AGENT_CONTACT = "caique.flima@gmail.com"

_RETRY_DELAYS = [2, 5, 10]


def fingerprint(path: Path) -> str:
    """Return the raw AcoustID fingerprint string for the audio file at *path*."""
    _duration, fp = acoustid.fingerprint_file(str(path))
    return fp


def lookup_musicbrainz(path: Path, acoustid_api_key: str) -> "Track | None":
    """Fingerprint *path* via AcoustID and look up metadata on MusicBrainz.

    Returns a populated :class:`Track` for the best match, or ``None`` when no
    match is found.  The ``cover_art`` field is intentionally left empty — it is
    filled in by Phase 3.
    """
    musicbrainzngs.set_useragent(_USER_AGENT_APP, _USER_AGENT_VERSION, _USER_AGENT_CONTACT)

    results = list(
        acoustid.match(acoustid_api_key, str(path), meta="recordings releasegroups")
    )

    if not results:
        return None

    # acoustid.match yields (score, recording_id, title, artist) tuples when
    # meta="recordings" is used, but with meta="recordings releasegroups" the
    # library may yield raw result dicts instead.  Handle both shapes.
    best = results[0]

    # When pyacoustid returns raw dicts we get the full nested structure.
    if isinstance(best, dict):
        recordings = best.get("recordings", [])
        if not recordings:
            return None
        recording = recordings[0]

        mb_id = recording.get("id", "")
        title = recording.get("title", "")

        artists = recording.get("artists", [])
        artist = artists[0].get("name", "") if artists else ""

        releases = recording.get("releases", [])
        release = releases[0] if releases else {}

        album = release.get("title", "")
        date_str = release.get("date", "")
        year = date_str[:4] if date_str else ""

        mediums = release.get("mediums", [{}])
        medium = mediums[0] if mediums else {}
        tracks = medium.get("tracks", [{}])
        track_entry = tracks[0] if tracks else {}
        track_number = track_entry.get("position", 0)
    else:
        # Simpler tuple form: (score, recording_id, title, artist)
        _score, mb_id, title, artist = best[:4]
        album = ""
        year = ""
        track_number = 0

    return Track(
        path=path,
        artist=artist,
        album=album,
        year=year,
        title=title,
        track_number=track_number,
        musicbrainz_recording_id=mb_id,
    )


def identify(path: Path, acoustid_api_key: str) -> Track:
    """Identify a track by fingerprint, retrying on transient server errors.

    Returns the best matching Track, or an empty Track on no match.
    Raises acoustid.WebServiceError if all retries are exhausted.
    """
    last_exc: Exception | None = None
    for delay in [0] + _RETRY_DELAYS:
        if delay:
            time.sleep(delay)
        try:
            result = lookup_musicbrainz(path, acoustid_api_key)
            return result if result is not None else Track(path=path)
        except acoustid.WebServiceError as exc:
            # Only retry on 503 Service Unavailable
            if "503" not in str(exc):
                raise
            last_exc = exc

    raise last_exc
