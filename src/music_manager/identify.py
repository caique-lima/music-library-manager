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


def _derive_album_artist(artist: str) -> str:
    """Strip the feat. portion from artist to produce an album artist.

    Returns '' for solo artists (no feat. separator detected); organize.py
    then falls back to the full artist field.
    """
    lower = artist.lower()
    for sep in (" feat. ", " feat ", " ft. ", " ft ", " featuring "):
        idx = lower.find(sep)
        if idx != -1:
            return artist[:idx].strip()
    return ""


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


def _fetch_from_musicbrainz(mb_id: str, path: Path) -> "Track | None":
    """Full MusicBrainz recording lookup by ID.

    Used when AcoustID returns the simplified tuple form, which lacks album,
    year, track number, and full artist credits.
    """
    try:
        result = musicbrainzngs.get_recording_by_id(
            mb_id,
            includes=["artists", "releases", "media"],
        )
    except musicbrainzngs.WebServiceError:
        return None

    recording = result.get("recording", {})
    title = recording.get("title", "")

    # Assemble full credited artist string with join phrases.
    artist_credit = recording.get("artist-credit", [])
    if artist_credit:
        artist = "".join(
            entry["artist"]["name"] + entry.get("joinphrase", "")
            for entry in artist_credit
            if isinstance(entry, dict) and "artist" in entry
        ).strip()
    else:
        artist = ""

    # Prefer a release that has a date; fall back to first in list.
    release_list = recording.get("release-list", [])
    release = next(
        (r for r in release_list if r.get("date")),
        release_list[0] if release_list else {},
    )

    album = release.get("title", "")
    year = (release.get("date") or "")[:4]

    track_number = 0
    medium_list = release.get("medium-list", [])
    if medium_list:
        track_list = medium_list[0].get("track-list", [])
        if track_list:
            pos = track_list[0].get("position", "0")
            track_number = int(pos) if str(pos).isdigit() else 0

    artist = _normalize_feat(artist)
    album_artist = _normalize_feat(_derive_album_artist(artist))

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

        artists = recording.get("artists", [])
        artist = _normalize_feat(_join_artists(artists))

        releases = recording.get("releases", [])
        release = _best_release(releases)

        album = release.get("title", "")
        year = (release.get("date") or "")[:4]

        mediums = release.get("mediums", [])
        medium = mediums[0] if mediums else {}
        tracks_on_medium = medium.get("tracks", [])
        track_entry = tracks_on_medium[0] if tracks_on_medium else {}
        track_number = track_entry.get("position", 0)

        album_artist = _normalize_feat(_derive_album_artist(artist))

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

    # Tuple form: (score, recording_id, title, artist) — delegate to MusicBrainz
    # for full metadata since the tuple carries no album/year/track info.
    _score, mb_id = best[0], best[1]
    if not mb_id:
        return None
    return _fetch_from_musicbrainz(mb_id, path)


def identify(path: Path, acoustid_api_key: str | None = None, use_shazam: bool = False) -> Track:
    """Identify a track, trying AcoustID first then optionally falling back to Shazam.

    Returns the best matching Track, or an empty Track if nothing matched.
    Pass ``use_shazam=True`` to enable the Shazam fallback (slower — requires
    audio extraction for each file).
    """
    if acoustid_api_key:
        try:
            result = lookup_musicbrainz(path, acoustid_api_key)
            if result is not None:
                _itunes_search_enrich(result)
                return result
        except acoustid.WebServiceError:
            pass

    if use_shazam:
        from music_manager.shazam import identify_shazam  # noqa: PLC0415
        shazam_result = identify_shazam(path)
        if shazam_result is not None:
            return shazam_result

    return Track(path=path)
