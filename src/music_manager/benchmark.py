"""Ground-truth benchmark: identify tracks from an organized library and compare against
embedded m4a tags.

The organized library (e.g. ~/personal_rips) already has correct tags written into each
file.  This module reads those tags as ground truth, runs identify() on the same audio,
and measures per-field accuracy.
"""

from __future__ import annotations

import re
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from mutagen.mp4 import MP4

from .identify import identify
from .track import Track

# Strip edition / variant parentheticals before fuzzy comparison so that
# "Operation: Mindcrime (Bonus Track Version)" still matches "Operation: Mindcrime".
_EDITION_RE = re.compile(
    r"\s*\((?:bonus track(?: version)?|remaster(?:ed)?|deluxe.*?|expanded.*?|"
    r"anniversary.*?|special.*?edition|original.*?(?:version|motion picture soundtrack)|"
    r"complete edition.*?|alternate lyrics|alt\.? lyrics|instrumental.*?|"
    r"censored.*?|clean.*?version|digital.*?dub|live)[^)]*\)\s*",
    re.IGNORECASE,
)
# Square-bracket labels to strip: [feat. X], [Skit], [Interlude], [Bonus Track]
_BRACKET_STRIP_RE = re.compile(
    r"\s*\[(?:feat\.[^\]]*|skit|interlude|bonus track[^\]]*|live[^\]]*)\]\s*",
    re.IGNORECASE,
)
# Round-bracket feat. credits in titles: (feat. X)
_PAREN_FEAT_RE = re.compile(r"\s*\(feat\.[^)]*\)\s*", re.IGNORECASE)
# Non-parenthetical subtitle separators common in soundtrack/edition album names:
#   "TRON: Legacy: Original Motion Picture Soundtrack"
#   "TRON: Legacy - The Complete Edition (Original Motion Picture Soundtrack)"
_NON_PAREN_SUFFIX_RE = re.compile(
    r"\s*[:\-]\s*(?:the complete edition.*|original motion picture soundtrack.*|"
    r"complete edition.*)$",
    re.IGNORECASE,
)
# "Pt." / "Part" normalisation so "Encom, Pt. II" matches "ENCOM Part II"
_PT_RE = re.compile(r"\bpt\.?\s+", re.IGNORECASE)


def _normalize(s: str) -> str:
    """Lowercase, strip edition/feat parentheticals, collapse whitespace."""
    s = _EDITION_RE.sub(" ", s)
    s = _BRACKET_STRIP_RE.sub(" ", s)
    s = _PAREN_FEAT_RE.sub(" ", s)
    s = _NON_PAREN_SUFFIX_RE.sub("", s)
    s = _PT_RE.sub("part ", s)
    return re.sub(r"\s+", " ", s.lower()).strip()


def _is_medley_component(a: str, b: str) -> bool:
    """Return True when one string is a '/' component of the other.

    Handles cases like "Burnin' / Too Long (Live)" being identified as just
    "Too Long" — the identified title is contained in the medley title.
    """
    if "/" not in a and "/" not in b:
        return False
    for medley, part in [(a, b), (b, a)]:
        if "/" in medley:
            components = [c.strip().lower() for c in medley.split("/")]
            part_norm = _normalize(part)
            if any(_similarity(part_norm, _normalize(c)) >= 0.85 for c in components):
                return True
    return False


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def _field_match(a: str, b: str, threshold: float = 0.85) -> bool:
    return _similarity(a, b) >= threshold or _is_medley_component(a, b)


@dataclass
class GroundTruth:
    path: Path
    title: str = ""
    artist: str = ""
    album_artist: str = ""
    album: str = ""
    year: str = ""
    track_number: int = 0


@dataclass
class BenchmarkResult:
    path: Path
    album_dir: str
    ground_truth: GroundTruth
    identified: Track
    source: str             # "acoustid" | "shazam" | "none"

    title_match: bool = False
    artist_match: bool = False
    album_match: bool = False
    album_artist_match: bool = False
    year_match: bool = False

    title_sim: float = 0.0
    artist_sim: float = 0.0
    album_sim: float = 0.0

    @property
    def perfect_match(self) -> bool:
        return self.title_match and self.artist_match and self.album_match

    def to_dict(self) -> dict:
        gt = self.ground_truth
        idf = self.identified
        return {
            "path": str(self.path),
            "album_dir": self.album_dir,
            "source": self.source,
            "ground_truth": {
                "title": gt.title,
                "artist": gt.artist,
                "album_artist": gt.album_artist,
                "album": gt.album,
                "year": gt.year,
            },
            "identified": {
                "title": idf.title,
                "artist": idf.artist,
                "album_artist": idf.album_artist,
                "album": idf.album,
                "year": idf.year,
                "acoustid_score": round(idf.acoustid_score, 3),
            },
            "match": {
                "title": self.title_match,
                "artist": self.artist_match,
                "album": self.album_match,
                "album_artist": self.album_artist_match,
                "year": self.year_match,
                "perfect": self.perfect_match,
            },
            "similarity": {
                "title": round(self.title_sim, 3),
                "artist": round(self.artist_sim, 3),
                "album": round(self.album_sim, 3),
            },
        }


def read_ground_truth(path: Path) -> GroundTruth:
    """Read embedded m4a tags and return a GroundTruth instance."""
    try:
        audio = MP4(str(path))
        tags = audio.tags or {}
    except Exception:
        return GroundTruth(path=path)

    def _get(key: str) -> str:
        vals = tags.get(key)
        return str(vals[0]) if vals else ""

    trkn = tags.get("trkn")
    track_number = int(trkn[0][0]) if trkn else 0
    day = _get("©day")
    year = day[:4] if day and day[:4].isdigit() else ""

    return GroundTruth(
        path=path,
        title=_get("©nam"),
        artist=_get("©ART"),
        album_artist=_get("aART"),
        album=_get("©alb"),
        year=year,
        track_number=track_number,
    )


def _detect_source(track: Track) -> str:
    if track.acoustid_score > 0 or track.musicbrainz_recording_id:
        return "acoustid"
    if track.title:
        return "shazam"
    return "none"


def benchmark_track(
    path: Path,
    acoustid_api_key: str | None,
    include_shazam: bool = True,
    library_root: Path | None = None,
) -> BenchmarkResult:
    """Identify one track and compare against its embedded ground-truth tags."""
    gt = read_ground_truth(path)

    try:
        identified = identify(path, acoustid_api_key)
    except Exception:
        identified = Track(path=path)

    source = _detect_source(identified)

    if library_root:
        try:
            album_dir = str(path.relative_to(library_root).parent)
        except ValueError:
            album_dir = path.parent.name
    else:
        album_dir = path.parent.name

    title_sim = _similarity(identified.title, gt.title)
    artist_sim = _similarity(identified.artist, gt.artist)
    album_sim = _similarity(identified.album, gt.album)

    # album_artist: fall back to track artist when either side is blank
    id_aa = identified.album_artist or identified.artist
    gt_aa = gt.album_artist or gt.artist

    return BenchmarkResult(
        path=path,
        album_dir=album_dir,
        ground_truth=gt,
        identified=identified,
        source=source,
        title_match=_field_match(identified.title, gt.title),
        artist_match=_field_match(identified.artist, gt.artist),
        album_match=_field_match(identified.album, gt.album),
        album_artist_match=_field_match(id_aa, gt_aa),
        year_match=bool(identified.year and gt.year and identified.year[:4] == gt.year[:4]),
        title_sim=title_sim,
        artist_sim=artist_sim,
        album_sim=album_sim,
    )


def build_benchmark_report(results: list[BenchmarkResult]) -> dict:
    """Aggregate a list of BenchmarkResults into a structured report dict."""
    total = len(results)
    if not total:
        return {"summary": {"total_tracks": 0}, "per_album": [], "failures": [], "all_results": []}

    perfect = sum(1 for r in results if r.perfect_match)
    title_ok = sum(1 for r in results if r.title_match)
    artist_ok = sum(1 for r in results if r.artist_match)
    album_ok = sum(1 for r in results if r.album_match)
    aa_ok = sum(1 for r in results if r.album_artist_match)
    year_ok = sum(1 for r in results if r.year_match)

    by_source: dict[str, int] = defaultdict(int)
    for r in results:
        by_source[r.source] += 1

    # Per-album aggregation
    by_album: dict[str, list[BenchmarkResult]] = defaultdict(list)
    for r in results:
        by_album[r.album_dir].append(r)

    per_album = []
    for album_dir, arecs in sorted(by_album.items()):
        n = len(arecs)
        alb_src: dict[str, int] = defaultdict(int)
        for r in arecs:
            alb_src[r.source] += 1
        per_album.append({
            "album_dir": album_dir,
            "track_count": n,
            "perfect_match_pct": round(sum(1 for r in arecs if r.perfect_match) / n * 100, 1),
            "title_match_pct": round(sum(1 for r in arecs if r.title_match) / n * 100, 1),
            "artist_match_pct": round(sum(1 for r in arecs if r.artist_match) / n * 100, 1),
            "album_match_pct": round(sum(1 for r in arecs if r.album_match) / n * 100, 1),
            "sources": dict(alb_src),
            "avg_title_sim": round(statistics.mean(r.title_sim for r in arecs), 3),
            "avg_album_sim": round(statistics.mean(r.album_sim for r in arecs), 3),
        })

    # Failures: tracks that didn't get a perfect match, sorted by worst combined similarity
    failures = sorted(
        (r for r in results if not r.perfect_match),
        key=lambda r: r.title_sim + r.artist_sim + r.album_sim,
    )

    return {
        "summary": {
            "total_tracks": total,
            "perfect_match_count": perfect,
            "perfect_match_pct": round(perfect / total * 100, 1),
            "title_match_pct": round(title_ok / total * 100, 1),
            "artist_match_pct": round(artist_ok / total * 100, 1),
            "album_match_pct": round(album_ok / total * 100, 1),
            "album_artist_match_pct": round(aa_ok / total * 100, 1),
            "year_match_pct": round(year_ok / total * 100, 1),
            "by_source": dict(by_source),
        },
        "per_album": per_album,
        "failures": [r.to_dict() for r in failures],
        "all_results": [r.to_dict() for r in results],
    }
