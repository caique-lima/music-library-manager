import json
import re
from pathlib import Path
from urllib.parse import urlencode

import acoustid
import musicbrainzngs

from music_manager.track import Track
from music_manager.cache import fetch_url

_USER_AGENT_APP = "music-library-manager"
_USER_AGENT_VERSION = "0.1"
_USER_AGENT_CONTACT = "https://github.com/caique-lima/music-library-manager"

# Normalize "Featuring" / "Ft." variants to a single canonical form.
_FEAT_RE = re.compile(r"\s+(Featuring|Ft\.?)\s+", re.IGNORECASE)


def _normalize_feat(s: str) -> str:
    return _FEAT_RE.sub(" feat. ", s)


def _join_artists(artists: list[dict]) -> str:
    """Join multiple AcoustID artist entries into a credited string."""
    names = [a.get("name", "") for a in artists if a.get("name")]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return names[0] + " feat. " + " feat. ".join(names[1:])


# Release-type preference for AcoustID response format (lower score = preferred).
_RELEASE_TYPE_SCORE = {"Album": 0, "Single": 1, "EP": 1, "": 2, "Broadcast": 3, "Other": 3}


def _score_release(release: dict) -> tuple:
    """Sort key for an AcoustID release dict: prefer studio albums."""
    rgs = release.get("releasegroups", [])
    rg = rgs[0] if rgs else {}
    release_type = rg.get("type", "")
    secondary_types = rg.get("secondarytypes", [])

    secondary_penalty = 10 if any(t in ("Live", "Compilation") for t in secondary_types) else 0
    type_score = _RELEASE_TYPE_SCORE.get(release_type, 2)
    has_no_date = 0 if release.get("date") else 1

    return (secondary_penalty, type_score, has_no_date)


def _best_release(releases: list) -> dict:
    """Return the preferred release from an AcoustID releases list."""
    if not releases:
        return {}
    return min(releases, key=_score_release)


# MusicBrainz medium formats that are audio-only (lower score = preferred).
_MB_FORMAT_SCORE = {
    "CD": 0, "Vinyl": 0, "12\" Vinyl": 0, "7\" Vinyl": 0, "10\" Vinyl": 0,
    "Digital Media": 0, "Cassette": 1,
    "DVD": 5, "DVD-Video": 5, "Blu-ray": 5, "VHS": 5,
}


def _score_mb_release(release: dict) -> tuple:
    """Sort key for a MusicBrainz release dict: prefer audio formats, non-VA, earlier dates."""
    medium_list = release.get("medium-list", [])
    fmt = medium_list[0].get("format", "") if medium_list else ""
    format_score = _MB_FORMAT_SCORE.get(fmt, 0)

    artist_credit = release.get("artist-credit", [])
    va_penalty = 5 if any(
        isinstance(e, dict) and e.get("artist", {}).get("name") == "Various Artists"
        for e in artist_credit
    ) else 0

    has_no_date = 0 if release.get("date") else 1
    date = release.get("date", "")
    year = int(date[:4]) if date and date[:4].isdigit() else 9999

    return (va_penalty, format_score, has_no_date, year)


def _best_mb_release(release_list: list) -> dict:
    """Return the preferred release from a MusicBrainz release-list."""
    if not release_list:
        return {}
    return min(release_list, key=_score_mb_release)


def _fetch_mb_data(mb_id: str) -> "tuple[dict, dict] | None":
    """Fetch a MusicBrainz recording and its best release. Returns (recording, release) or None."""
    try:
        result = musicbrainzngs.get_recording_by_id(
            mb_id,
            includes=["artists", "releases", "media", "artist-credits"],
        )
    except musicbrainzngs.WebServiceError:
        return None
    recording = result.get("recording", {})
    if not recording:
        return None
    release = _best_mb_release(recording.get("release-list", []))
    return recording, release


def _build_track_from_mb(mb_id: str, recording: dict, release: dict, path: Path) -> Track:
    """Build a Track from a MusicBrainz recording and its chosen release."""
    title = recording.get("title", "")

    # Use release-level artist credit (album artist, no feat. credits).
    # Fall back to recording-level if the release has none or is a VA compilation.
    release_credit = release.get("artist-credit", [])
    is_va = any(
        isinstance(e, dict) and e.get("artist", {}).get("name") == "Various Artists"
        for e in release_credit
    )
    artist_credit = (release_credit if release_credit and not is_va
                     else recording.get("artist-credit", []))
    artist = _normalize_feat(_join_artists([
        e["artist"] for e in artist_credit
        if isinstance(e, dict) and "artist" in e
    ]))

    album = release.get("title", "")
    year = (release.get("date") or "")[:4]

    track_number = 0
    medium_list = release.get("medium-list", [])
    if medium_list:
        track_list = medium_list[0].get("track-list", [])
        if track_list:
            pos = track_list[0].get("position", "0")
            track_number = int(pos) if str(pos).isdigit() else 0

    return Track(
        path=path,
        artist=artist,
        album_artist="",
        album=album,
        year=year,
        title=title,
        track_number=track_number,
        musicbrainz_recording_id=mb_id,
    )


def _fetch_from_musicbrainz(mb_id: str, path: Path) -> "Track | None":
    """Full MusicBrainz recording lookup by ID.

    Used when AcoustID returns the simplified tuple form, which lacks album,
    year, track number, and full artist credits.
    """
    data = _fetch_mb_data(mb_id)
    if data is None:
        return None
    recording, release = data
    return _build_track_from_mb(mb_id, recording, release, path)


_ITUNES_SEARCH_URL = "https://itunes.apple.com/search"


def _itunes_search_enrich(track: Track) -> None:
    """Fill empty genre/album/album_artist/year fields using an iTunes text search.

    Mutates *track* in place. No-ops when all target fields are already
    populated or when the track lacks enough data to form a useful query.
    """
    if track.genre and track.album and track.album_artist:
        return
    if not track.title or not track.artist:
        return

    url = _ITUNES_SEARCH_URL + "?" + urlencode({
        "term": f"{track.artist} {track.title}",
        "entity": "song",
        "limit": 5,
    })
    raw = fetch_url(url)
    if not raw:
        return

    try:
        results = json.loads(raw).get("results", [])
    except Exception:
        return

    # Prefer an exact title match; fall back to the first result.
    match = next(
        (r for r in results if r.get("trackName", "").lower() == track.title.lower()),
        results[0] if results else None,
    )
    if not match:
        return

    if not track.genre:
        track.genre = match.get("primaryGenreName", "")
    if not track.album:
        track.album = match.get("collectionName", "")
    if not track.album_artist:
        track.album_artist = match.get("collectionArtistName", "")
    if not track.year:
        track.year = (match.get("releaseDate") or "")[:4]


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
        acoustid.match(acoustid_api_key, str(path), meta="recordings releases releasegroups tracks")
    )

    if not results:
        return None

    # acoustid.match yields (score, recording_id, title, artist) tuples when
    # meta="recordings" is used, but with richer meta flags it returns dicts.
    best = results[0]

    if isinstance(best, dict):
        recordings = best.get("recordings", [])
        if not recordings:
            return None
        recording = recordings[0]

        mb_id = recording.get("id", "")
        title = recording.get("title", "")

        releases = recording.get("releases", [])
        release = _best_release(releases)

        # Use release-level artists (album artist, no feat. credits).
        # Fall back to recording-level if the release has none.
        release_artists = release.get("artists") or recording.get("artists", [])
        artist = _normalize_feat(_join_artists(release_artists))

        album = release.get("title", "")
        year = (release.get("date") or "")[:4]

        mediums = release.get("mediums", [])
        medium = mediums[0] if mediums else {}
        tracks_on_medium = medium.get("tracks", [])
        track_entry = tracks_on_medium[0] if tracks_on_medium else {}
        track_number = track_entry.get("position", 0)

        album_artist = ""

        return Track(
            path=path,
            artist=artist,
            album_artist=album_artist,
            album=album,
            year=year,
            title=title,
            track_number=track_number,
            musicbrainz_recording_id=mb_id,
        )

    # Tuple form: (score, recording_id, title, artist) — try up to 3 unique
    # recording IDs and return the one whose best MusicBrainz release scores
    # lowest under _score_mb_release (prefers audio formats, non-VA, earlier dates).
    seen: set[str] = set()
    best_candidate: "tuple[str, dict, dict] | None" = None
    best_candidate_score: tuple = (99,) * 4

    for result in results:
        if len(seen) >= 3:
            break
        mb_id = result[1] if not isinstance(result, dict) else None
        if not mb_id or mb_id in seen:
            continue
        seen.add(mb_id)

        data = _fetch_mb_data(mb_id)
        if data is None:
            continue
        recording, release = data
        score = _score_mb_release(release) if release else (99,) * 4
        if best_candidate is None or score < best_candidate_score:
            best_candidate_score = score
            best_candidate = (mb_id, recording, release)

    if best_candidate is None:
        return None
    mb_id, recording, release = best_candidate
    return _build_track_from_mb(mb_id, recording, release, path)


def identify(path: Path, acoustid_api_key: str | None = None) -> Track:
    """Identify a track via AcoustID + MusicBrainz.

    Returns the best matching Track, or an empty Track if nothing matched.
    """
    if acoustid_api_key:
        try:
            result = lookup_musicbrainz(path, acoustid_api_key)
            if result is not None:
                _itunes_search_enrich(result)
                return result
        except acoustid.WebServiceError:
            pass

    return Track(path=path)
