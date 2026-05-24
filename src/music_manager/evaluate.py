"""Read-only evaluation of metadata identification accuracy.

Fingerprints WAV files directly — no conversion performed.
"""

import asyncio
import re
from dataclasses import dataclass, field
from pathlib import Path

import acoustid

from .track import Track
from .identify import identify

try:
    from shazamio import Shazam as _Shazam
    _HAS_SHAZAM = True
except ImportError:
    _HAS_SHAZAM = False

_RECORD_RE = re.compile(r'^TRK\d+~(\d+)\.WAV$', re.IGNORECASE)


def parse_record_index(path: Path) -> str:
    """Return "base" for TRK3.WAV, or the record number string for TRK3~1.WAV."""
    m = _RECORD_RE.match(path.name)
    return m.group(1) if m else "base"


@dataclass
class ShazamMatch:
    title: str = ""
    artist: str = ""
    album: str = ""
    year: str = ""
    genre: str = ""
    cover_url: str = ""
    confidence: float = 0.0   # 0–1, from Shazam's "score" field if present
    raw: dict = field(default_factory=dict, repr=False)


@dataclass
class EvalResult:
    path: Path
    record_index: str        # "base", "0", "1", …
    current: Track           # result from current AcoustID→MB→iTunes pipeline
    shazam: ShazamMatch | None = None

    def to_dict(self) -> dict:
        def _track_dict(t: Track) -> dict:
            return {
                "title": t.title,
                "artist": t.artist,
                "album": t.album,
                "album_artist": t.album_artist,
                "year": t.year,
                "track_number": t.track_number,
                "genre": t.genre,
                "has_cover_art": bool(t.cover_art),
                "acoustid_score": t.acoustid_score,
                "mb_recording_id": t.musicbrainz_recording_id,
                "mb_release_id": t.musicbrainz_release_id,
            }

        d: dict = {
            "path": str(self.path),
            "filename": self.path.name,
            "record_index": self.record_index,
            "current_pipeline": _track_dict(self.current),
        }
        if self.shazam is not None:
            d["shazam"] = {
                "title": self.shazam.title,
                "artist": self.shazam.artist,
                "album": self.shazam.album,
                "year": self.shazam.year,
                "genre": self.shazam.genre,
                "confidence": self.shazam.confidence,
            }
        else:
            d["shazam"] = None
        return d


async def _shazam_recognize_async(path: Path) -> ShazamMatch | None:
    shazam = _Shazam()
    try:
        result = await shazam.recognize(str(path))
    except Exception:
        return None
    if not result:
        return None

    track_data = result.get("track", {})
    if not track_data:
        return None

    title = track_data.get("title", "")
    artist = track_data.get("subtitle", "")

    sections = track_data.get("sections", [])
    metadata = {}
    for section in sections:
        for item in section.get("metadata", []):
            metadata[item.get("title", "").lower()] = item.get("text", "")

    album = metadata.get("album", "")
    year = metadata.get("released", "")[:4] if metadata.get("released") else ""
    genre = track_data.get("genres", {}).get("primary", "")
    cover_url = track_data.get("images", {}).get("coverarthq", "") or track_data.get("images", {}).get("coverart", "")
    confidence = float(result.get("matches", [{}])[0].get("frequencynameloc", 0)) / 10000.0 if result.get("matches") else 0.0

    return ShazamMatch(
        title=title,
        artist=artist,
        album=album,
        year=year,
        genre=genre,
        cover_url=cover_url,
        confidence=min(confidence, 1.0),
        raw=result,
    )


def _shazam_recognize(path: Path) -> ShazamMatch | None:
    if not _HAS_SHAZAM:
        return None
    try:
        return asyncio.run(_shazam_recognize_async(path))
    except Exception:
        return None


def evaluate_track(
    path: Path,
    acoustid_api_key: str | None,
    include_shazam: bool = True,
) -> EvalResult:
    """Identify a WAV file via current pipeline and optionally Shazam.

    Never converts or modifies the input file.
    """
    try:
        current = identify(path, acoustid_api_key)
    except (acoustid.WebServiceError, acoustid.FingerprintGenerationError, Exception):
        current = Track(path=path)

    shazam_match = None
    if include_shazam:
        shazam_match = _shazam_recognize(path)

    return EvalResult(
        path=path,
        record_index=parse_record_index(path),
        current=current,
        shazam=shazam_match,
    )
