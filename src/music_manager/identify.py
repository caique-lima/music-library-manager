import json
import re
from pathlib import Path
from urllib.parse import urlencode

import acoustid
import musicbrainzngs
from mutagen import File as _MutagenFile

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


def _score_release(release: dict, recording_title: str = "") -> tuple:
    """Sort key for an AcoustID release dict: prefer studio albums."""
    rgs = release.get("releasegroups", [])
    rg = rgs[0] if rgs else {}
    release_type = rg.get("type", "")
    secondary_types = rg.get("secondarytypes", [])

    secondary_penalty = 10 if any(t in ("Compilation",) for t in secondary_types) else 0
    type_score = _RELEASE_TYPE_SCORE.get(release_type, 2)
    has_no_date = 0 if release.get("date") else 1

    # Penalise self-titled releases (e.g. a "Da Funk" single when we want the
    # "Homework" album).  AcoustID data sometimes labels singles as type "Album".
    self_titled = (
        1 if recording_title
        and release.get("title", "").lower().strip() == recording_title.lower().strip()
        else 0
    )

    # Track-count tiebreaker: AcoustID includes per-medium track lists when
    # meta="tracks" is requested.  Sum them; cap at 30 so mega-compilations
    # don't dominate after they're already penalised by secondary_penalty.
    mediums = release.get("mediums", [])
    track_count = sum(len(m.get("tracks", [])) for m in mediums)
    track_count_score = -min(track_count, 30)

    return (secondary_penalty, type_score + self_titled, has_no_date, track_count_score)


def _is_studio_album(release: dict) -> bool:
    """Return True when a release belongs to a non-live, non-compilation Album group."""
    rgs = release.get("releasegroups", [])
    rg = rgs[0] if rgs else {}
    return (
        rg.get("type", "") == "Album"
        and not any(t in ("Live", "Compilation") for t in rg.get("secondarytypes", []))
    )


def _best_release(releases: list, recording_title: str = "") -> dict:
    """Return the preferred release from an AcoustID releases list.

    When any studio-album release exists, singles and EPs are excluded so they
    can never beat the canonical album — the main cause of "Single name as album"
    mis-identification.
    """
    if not releases:
        return {}
    album_releases = [r for r in releases if _is_studio_album(r)]
    return min(
        album_releases or releases,
        key=lambda r: _score_release(r, recording_title),
    )


# MusicBrainz medium formats that are audio-only (lower score = preferred).
_MB_FORMAT_SCORE = {
    "CD": 0, "Vinyl": 0, "12\" Vinyl": 0, "7\" Vinyl": 0, "10\" Vinyl": 0,
    "Digital Media": 0, "Cassette": 1,
    "DVD": 5, "DVD-Video": 5, "Blu-ray": 5, "VHS": 5,
}

# Release-group type penalty for MusicBrainz releases (lower = preferred).
_MB_RG_TYPE_SCORE = {"Album": 0, "EP": 2, "Single": 5, "Broadcast": 8, "Other": 8}


def _score_mb_release(release: dict) -> tuple:
    """Sort key for a MusicBrainz release dict: prefer studio albums, audio formats, non-VA."""
    medium_list = release.get("medium-list", [])
    fmt = medium_list[0].get("format", "") if medium_list else ""
    format_score = _MB_FORMAT_SCORE.get(fmt, 0)

    artist_credit = release.get("artist-credit", [])
    va_penalty = 5 if any(
        isinstance(e, dict) and e.get("artist", {}).get("name") == "Various Artists"
        for e in artist_credit
    ) else 0

    # Release-group type: prefer Album over Single/EP (populated when includes
    # contain "release-groups" in the MusicBrainz recording query).
    rg = release.get("release-group", {}) or {}
    rg_type = rg.get("type", "") or rg.get("primary-type", "")
    rg_secondary = rg.get("secondary-type-list", []) or []
    rg_penalty = _MB_RG_TYPE_SCORE.get(rg_type, 1)
    if any(t in ("Compilation", "Live") for t in rg_secondary):
        rg_penalty += 10

    # Penalise releases whose title contains "Instrumental" — avoids picking
    # the instrumental variant of an album ("2001: Instrumentals") over the
    # canonical release ("2001").
    if "instrumental" in release.get("title", "").lower():
        rg_penalty += 5

    has_no_date = 0 if release.get("date") else 1
    date = release.get("date", "")
    year = int(date[:4]) if date and date[:4].isdigit() else 9999

    # Track-count tiebreaker: prefer releases with more tracks so a full album
    # beats a single/EP when release-group types are otherwise equal.
    track_count = sum(int(m.get("track-count", 0) or 0) for m in medium_list)
    # Negative: fewer tracks → higher (worse) score.
    track_count_score = -min(track_count, 30)

    return (va_penalty, rg_penalty, format_score, has_no_date, year, track_count_score)


def _duration_diff_s(path: Path, recording: dict) -> int:
    """Return abs(file_duration - recording_duration) in whole seconds.

    Returns 30 when either side has no duration data — a neutral penalty
    that loses to any recording with a known, close duration match but
    beats recordings whose durations are clearly wrong.
    """
    mb_ms = int(recording.get("length") or 0)
    if not mb_ms:
        return 30
    try:
        audio = _MutagenFile(str(path))
        file_ms = int(audio.info.length * 1000) if audio and audio.info else 0
    except Exception:
        return 30
    if not file_ms:
        return 30
    return abs(file_ms - mb_ms) // 1000


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
    except Exception:
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
        musicbrainz_release_id=release.get("id", ""),
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
    if track.genre and track.album and track.album_artist and track.cover_art:
        return
    if not track.title or not track.artist:
        return
    # Always ensure album_artist is populated after enrichment — even if iTunes
    # doesn't return collectionArtistName, fall back to track artist so the iPod
    # "Album Artist" tag is never blank.

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
        track.album_artist = match.get("collectionArtistName", "") or track.artist
    if not track.year:
        track.year = (match.get("releaseDate") or "")[:4]
    if not track.cover_art:
        artwork_url = match.get("artworkUrl100", "")
        if artwork_url:
            artwork_url = artwork_url.replace("100x100bb", "600x600bb")
            track.cover_art = fetch_url(artwork_url)


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
        acoustid_score = float(best.get("score", 0.0))
        recordings = best.get("recordings", [])
        if not recordings:
            return None
        recording = recordings[0]

        mb_id = recording.get("id", "")
        title = recording.get("title", "")

        releases = recording.get("releases", [])
        album_releases = [r for r in releases if _is_studio_album(r)]

        # AcoustID's compact response truncates release lists (typically ≤5 results),
        # so studio albums are often absent when the recording has many singles/EPs.
        # Fall back to a full MusicBrainz lookup to get the complete release list.
        if not album_releases and mb_id:
            mb_track = _fetch_from_musicbrainz(mb_id, path)
            if mb_track:
                mb_track.acoustid_score = acoustid_score
                return mb_track

        release = _best_release(releases, recording_title=title)

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
            musicbrainz_release_id=release.get("id", ""),
            acoustid_score=acoustid_score,
        )

    # Tuple form: (score, recording_id, title, artist) — try up to 6 unique
    # recording IDs and return the one whose best MusicBrainz release scores
    # lowest under _score_mb_release (prefers audio formats, non-VA, earlier dates).
    # Using 6 rather than 3 because AcoustID often returns 5-6 distinct recording
    # IDs with equal top scores; the canonical studio-album recording can easily
    # appear at index 4 while lower-indexed IDs resolve to compilations/DVDs.
    seen: set[str] = set()
    best_candidate: "tuple[str, dict, dict] | None" = None
    best_candidate_score: tuple = (99, 99, 99, 999, 0)  # (va, rg_type, format, dur_diff, -count)
    top_tuple_score: float = float(results[0][0]) if results and not isinstance(results[0], dict) else 0.0

    for result in results:
        if len(seen) >= 6:
            break
        mb_id = result[1] if not isinstance(result, dict) else None
        if not mb_id or mb_id in seen:
            continue
        seen.add(mb_id)

        data = _fetch_mb_data(mb_id)
        if data is None:
            continue
        recording, release = data
        # Score tuple (lower = better):
        #   [0-2] quality metrics (VA penalty, format, has no date)
        #   [3]   duration diff in seconds vs MB recording length — primary tiebreaker
        #   [4]   negative release count — secondary tiebreaker when duration is unknown
        release_count = len(recording.get("release-list", []))
        dur_diff = _duration_diff_s(path, recording)
        score = (_score_mb_release(release)[:3] + (dur_diff, -release_count)) if release else (99, 99, 99, 999, 0)
        if best_candidate is None or score < best_candidate_score:
            best_candidate_score = score
            best_candidate = (mb_id, recording, release)

    if best_candidate is None:
        return None
    mb_id, recording, release = best_candidate
    track = _build_track_from_mb(mb_id, recording, release, path)
    track.acoustid_score = top_tuple_score
    return track


def _should_prefer_shazam(acoustid_track: Track, shazam_track: "Track | None") -> bool:
    """Return True when Shazam's result is more trustworthy than AcoustID's.

    Two cases:
    1. Low AcoustID confidence (score < 0.4) — Shazam's direct recognition wins.
    2. Year gap > 5 years — AcoustID matched the right fingerprint but chose the
       wrong release (e.g. a 1992 compilation for a track whose canonical release
       is 1999).  Shazam's result is preferred in that case.
    """
    if shazam_track is None or not shazam_track.title:
        return False
    if 0 < acoustid_track.acoustid_score < 0.4:
        return True
    try:
        ay = int(acoustid_track.year)
        sy = int(shazam_track.year)
    except (ValueError, TypeError):
        return False
    return abs(ay - sy) > 5


def identify(path: Path, acoustid_api_key: str | None = None) -> Track:
    """Identify a track via AcoustID → MusicBrainz, with Shazam cross-check and fallback.

    Pipeline:
      1. AcoustID fingerprint → MusicBrainz metadata
      2. iTunes enrichment (fills genre, album_artist, cover art)
      3. Shazam cross-check: if AcoustID year differs from Shazam by >5 years,
         the AcoustID result matched the wrong release — swap to Shazam's result
      4. If AcoustID found nothing, Shazam is the primary source
      5. Guarantee album_artist is always set

    Returns the best matching Track, or an empty Track if nothing matched.
    """
    from .shazam import identify_via_shazam

    result: Track | None = None

    if acoustid_api_key:
        try:
            result = lookup_musicbrainz(path, acoustid_api_key)
        except Exception:
            pass

    if result is not None:
        _itunes_search_enrich(result)
        shazam_result = identify_via_shazam(path)
        if _should_prefer_shazam(result, shazam_result):
            result = shazam_result
    else:
        result = identify_via_shazam(path)

    if result is None:
        return Track(path=path)

    if result.title and not result.album_artist:
        result.album_artist = result.artist

    return result
