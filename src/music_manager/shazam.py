"""Shazam-based track identification with iTunes enrichment.

Used as a fallback when AcoustID fingerprinting returns no match.
"""
import asyncio
import json
from pathlib import Path
from urllib.parse import urlencode

from .track import Track
from .cache import fetch_url

try:
    from shazamio import Shazam as _Shazam
    _HAS_SHAZAM = True
except ImportError:
    _HAS_SHAZAM = False

_ITUNES_SEARCH_URL = "https://itunes.apple.com/search"


async def _recognize_async(path: Path) -> dict | None:
    shazam = _Shazam()
    try:
        return await shazam.recognize(str(path))
    except Exception:
        return None


def _recognize(path: Path) -> dict | None:
    """Synchronous wrapper — safe to call from threads (each call gets its own loop)."""
    if not _HAS_SHAZAM:
        return None
    try:
        return asyncio.run(_recognize_async(path))
    except Exception:
        return None


def _parse_shazam_result(result: dict) -> tuple[str, str, str, str, str, str]:
    """Return (title, artist, album, year, genre, artwork_url) from a Shazam result."""
    track = result.get("track", {})
    if not track:
        return "", "", "", "", "", ""

    title = track.get("title", "")
    artist = track.get("subtitle", "")

    metadata: dict = {}
    for section in track.get("sections", []):
        for item in section.get("metadata", []):
            metadata[item.get("title", "").lower()] = item.get("text", "")

    album = metadata.get("album", "")
    year = metadata.get("released", "")[:4] if metadata.get("released") else ""
    genre = track.get("genres", {}).get("primary", "")
    artwork_url = (
        track.get("images", {}).get("coverarthq", "")
        or track.get("images", {}).get("coverart", "")
    )
    return title, artist, album, year, genre, artwork_url


def _itunes_lookup(title: str, artist: str) -> dict:
    """Search iTunes for title+artist and return the best matching result dict."""
    if not title or not artist:
        return {}
    url = _ITUNES_SEARCH_URL + "?" + urlencode({
        "term": f"{artist} {title}",
        "entity": "song",
        "limit": 5,
    })
    raw = fetch_url(url)
    if not raw:
        return {}
    try:
        results = json.loads(raw).get("results", [])
    except Exception:
        return {}
    return next(
        (r for r in results if r.get("trackName", "").lower() == title.lower()),
        results[0] if results else {},
    )


def _itunes_confirms(title: str, artist: str, itunes: dict) -> bool:
    """Return True when an iTunes result plausibly confirms the Shazam title+artist.

    Only called when iTunes returned results.  Rejects Shazam hallucinations where
    Shazam "recognises" a track as something completely unrelated.
    """
    from difflib import SequenceMatcher

    def _sim(a: str, b: str) -> float:
        if not a or not b:
            return 0.0
        return SequenceMatcher(None, a.lower(), b.lower()).ratio()

    itunes_title = itunes.get("trackName", "")
    itunes_artist = itunes.get("artistName", "")
    # Accept if either title or artist matches with ≥ 0.5 similarity.
    # This preserves non-iTunes music (empty itunes result) while rejecting
    # cases where iTunes returned a very different song for the same query.
    return _sim(title, itunes_title) >= 0.5 or _sim(artist, itunes_artist) >= 0.5


def identify_via_shazam(path: Path) -> "Track | None":
    """Identify a track via Shazam and enrich with iTunes for track_number + album_artist.

    Returns a populated Track, or None if Shazam finds no match.
    """
    result = _recognize(path)
    if not result:
        return None

    title, artist, album, year, genre, artwork_url = _parse_shazam_result(result)
    if not title:
        return None

    itunes = _itunes_lookup(title, artist)

    # Reject Shazam hallucinations: if iTunes returned a result but it strongly
    # disagrees with what Shazam reported, the identification is unreliable.
    if itunes and not _itunes_confirms(title, artist, itunes):
        return None

    track_number = int(itunes.get("trackNumber") or 0)
    album_artist = itunes.get("collectionArtistName", "") or artist
    if not album:
        album = itunes.get("collectionName", "")
    if not year:
        year = (itunes.get("releaseDate") or "")[:4]
    if not genre:
        genre = itunes.get("primaryGenreName", "")

    # Prefer iTunes 600×600 art; fall back to Shazam's own artwork
    cover_art = b""
    itunes_art = itunes.get("artworkUrl100", "")
    if itunes_art:
        cover_art = fetch_url(itunes_art.replace("100x100bb", "600x600bb"))
    if not cover_art and artwork_url:
        cover_art = fetch_url(artwork_url)

    return Track(
        path=path,
        title=title,
        artist=artist,
        album=album,
        album_artist=album_artist,
        year=year,
        genre=genre,
        track_number=track_number,
        cover_art=cover_art,
    )
