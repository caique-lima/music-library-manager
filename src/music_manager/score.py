"""Aggregate EvalResult lists into a structured accuracy report."""

from __future__ import annotations

import statistics
from collections import defaultdict
from difflib import SequenceMatcher
from typing import Any

from .evaluate import EvalResult


def _fuzzy_match(a: str, b: str) -> float:
    """Return 0–1 similarity between two strings (case-insensitive)."""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _album_correct(identified_album: str, ground_truth_album: str, threshold: float = 0.8) -> bool:
    return _fuzzy_match(identified_album, ground_truth_album) >= threshold


def _best_known_match(album: str, artist: str, known_albums: list[dict]) -> dict | None:
    """Return the best-matching entry from known_albums for an identified album+artist.

    Scores each candidate as 60% album similarity + 40% artist similarity.
    Returns None when no candidate clears 0.5.
    """
    if not album or not known_albums:
        return None
    best_score = 0.0
    best = None
    for ka in known_albums:
        alb_sim = _fuzzy_match(album, ka.get("album", ""))
        art_sim = _fuzzy_match(artist, ka.get("artist", ""))
        combined = 0.6 * alb_sim + 0.4 * art_sim
        if combined > best_score:
            best_score = combined
            best = ka
    if best_score >= 0.5:
        return {**best, "_similarity": round(best_score, 3)}
    return None


def _ipod_score(track: Any, gt_album: str = "", gt_artist: str = "") -> float:
    """Return 0–10 iPod-weighted quality score for a track result dict."""
    score = 0.0
    if track.get("album_artist"):
        score += 3.0
    if track.get("track_number", 0) > 0:
        score += 3.0
    if gt_album and _album_correct(track.get("album", ""), gt_album):
        score += 2.0
    elif track.get("album"):
        score += 1.0
    if track.get("title"):
        score += 1.0
    if track.get("year"):
        score += 1.0
    return score


def _field_coverage(tracks: list[dict]) -> dict[str, float]:
    """Return % of tracks where each field is non-empty/non-zero."""
    if not tracks:
        return {}
    fields = ["title", "artist", "album", "album_artist", "year", "track_number", "genre", "has_cover_art"]
    return {
        f: round(sum(1 for t in tracks if t.get(f) and t.get(f) != 0) / len(tracks) * 100, 1)
        for f in fields
    }


def score_report(
    results: list[EvalResult],
    known_albums: list[dict] | None = None,
) -> dict:
    """Build a full evaluation report from a list of EvalResults.

    Args:
        results: Output from evaluate_track() for each file.
        known_albums: Optional flat list of {artist, album, year} dicts.
                      Loaded from eval/records.yaml ``known_albums`` key by the caller.
                      Each identified record is matched against this list by fuzzy
                      album+artist similarity — no index mapping required.
    """
    known_albums = known_albums or []

    # ── group by record index ────────────────────────────────────────────────
    by_record: dict[str, list[EvalResult]] = defaultdict(list)
    for r in results:
        by_record[r.record_index].append(r)

    per_record: list[dict] = []
    all_current: list[dict] = []
    all_shazam: list[dict] = []
    acoustid_scores: list[float] = []

    for rec_idx, rec_results in sorted(by_record.items(), key=lambda kv: (kv[0] != "base", kv[0])):
        current_dicts = [r.to_dict()["current_pipeline"] for r in rec_results]
        all_current.extend(current_dicts)

        shazam_dicts = [r.to_dict()["shazam"] for r in rec_results if r.shazam]
        all_shazam.extend(shazam_dicts)

        for r in rec_results:
            if r.current.acoustid_score > 0:
                acoustid_scores.append(r.current.acoustid_score)

        # Most-common identified album across tracks in this record
        album_votes: dict[str, int] = defaultdict(int)
        artist_votes: dict[str, int] = defaultdict(int)
        for cd in current_dicts:
            if cd.get("album"):
                album_votes[cd["album"]] += 1
            if cd.get("album_artist") or cd.get("artist"):
                artist_votes[cd.get("album_artist") or cd.get("artist", "")] += 1

        consensus_album = max(album_votes, key=album_votes.__getitem__) if album_votes else ""
        consensus_artist = max(artist_votes, key=artist_votes.__getitem__) if artist_votes else ""

        # Match against known list
        best_known = _best_known_match(consensus_album, consensus_artist, known_albums)
        gt_album = best_known.get("album", "") if best_known else ""
        gt_artist = best_known.get("artist", "") if best_known else ""

        # Per-track album accuracy vs best known match
        correct_album = sum(
            1 for cd in current_dicts
            if gt_album and _album_correct(cd.get("album", ""), gt_album)
        )
        album_accuracy = round(correct_album / len(current_dicts) * 100, 1) if gt_album else None

        # Album consistency: all tracks agree on album + album_artist?
        albums_seen = {cd.get("album", "") for cd in current_dicts if cd.get("album")}
        album_artists_seen = {cd.get("album_artist", "") for cd in current_dicts if cd.get("album_artist")}
        years_seen = {cd.get("year", "") for cd in current_dicts if cd.get("year")}
        is_consistent = len(albums_seen) <= 1 and len(album_artists_seen) <= 1

        # Track number completeness
        track_nums = sorted(cd.get("track_number", 0) for cd in current_dicts if cd.get("track_number", 0) > 0)
        has_number_gaps = track_nums != list(range(1, len(current_dicts) + 1)) and bool(track_nums)

        cover_art_pct = round(
            sum(1 for cd in current_dicts if cd.get("has_cover_art")) / len(current_dicts) * 100, 1
        )

        ipod_scores = [_ipod_score(cd, gt_album, gt_artist) for cd in current_dicts]

        # Shazam vs current album agreement for this record
        shazam_agreement = None
        shazam_with_album = [r for r in rec_results if r.shazam and r.shazam.album]
        if shazam_with_album:
            agreed = sum(
                1 for r in shazam_with_album
                if r.current.album and _album_correct(r.current.album, r.shazam.album)
            )
            shazam_agreement = round(agreed / len(shazam_with_album) * 100, 1)

        per_record.append({
            "record_index": rec_idx,
            "track_count": len(rec_results),
            "consensus_album": consensus_album,
            "consensus_artist": consensus_artist,
            "best_known_match": best_known,
            "album_accuracy_pct": album_accuracy,
            "album_consistent": is_consistent,
            "albums_identified": sorted(albums_seen),
            "album_artists_identified": sorted(album_artists_seen),
            "years_identified": sorted(years_seen),
            "track_number_gaps": has_number_gaps,
            "track_numbers_found": track_nums,
            "cover_art_pct": cover_art_pct,
            "shazam_agreement_pct": shazam_agreement,
            "ipod_score_avg": round(statistics.mean(ipod_scores), 2) if ipod_scores else 0.0,
            "ipod_score_min": round(min(ipod_scores), 2) if ipod_scores else 0.0,
        })

    # ── aggregate ────────────────────────────────────────────────────────────
    identified = sum(1 for r in results if r.current.title)
    shazam_identified = sum(1 for r in results if r.shazam and r.shazam.title)

    current_coverage = _field_coverage(all_current)
    shazam_coverage = _field_coverage([
        {
            "title": s.get("title"), "artist": s.get("artist"), "album": s.get("album"),
            "album_artist": "", "year": s.get("year"), "genre": s.get("genre"),
            "track_number": 0, "has_cover_art": bool(s.get("confidence")),
        }
        for s in all_shazam
    ]) if all_shazam else {}

    comparable = [r for r in results if r.current.album and r.shazam and r.shazam.album]
    cross_agreement = round(
        sum(1 for r in comparable if _album_correct(r.current.album, r.shazam.album))
        / len(comparable) * 100, 1
    ) if comparable else None

    acoustid_dist: dict = {}
    if acoustid_scores:
        sorted_scores = sorted(acoustid_scores)
        n = len(sorted_scores)
        acoustid_dist = {
            "count": n,
            "min": round(sorted_scores[0], 3),
            "p25": round(sorted_scores[n // 4], 3),
            "median": round(statistics.median(sorted_scores), 3),
            "p75": round(sorted_scores[n * 3 // 4], 3),
            "max": round(sorted_scores[-1], 3),
            "below_0_5": sum(1 for s in sorted_scores if s < 0.5),
        }

    # How many records were matched to a known album
    matched_records = sum(1 for pr in per_record if pr.get("best_known_match"))
    unmatched_albums = [
        ka for ka in known_albums
        if not any(
            (pr.get("best_known_match") or {}).get("album") == ka.get("album")
            for pr in per_record
        )
    ]

    # Failure modes per track
    failures: list[dict] = []
    for r in results:
        issues = []
        if not r.current.title:
            issues.append("no_title")
        if not r.current.album_artist:
            issues.append("no_album_artist")
        if 0 < r.current.acoustid_score < 0.5:
            issues.append("low_acoustid_score")
        if r.shazam and r.current.album and not _album_correct(r.current.album, r.shazam.album):
            issues.append("source_disagreement")
        if issues:
            failures.append({
                "file": r.path.name,
                "record_index": r.record_index,
                "issues": issues,
                "current_album": r.current.album,
                "shazam_album": r.shazam.album if r.shazam else None,
                "acoustid_score": round(r.current.acoustid_score, 3),
                "ipod_score": _ipod_score(r.to_dict()["current_pipeline"]),
            })

    recommendations: list[str] = []
    empty_aa = sum(1 for cd in all_current if not cd.get("album_artist"))
    if empty_aa > 0:
        recommendations.append(
            f"{round(empty_aa / len(all_current) * 100)}% of tracks have empty album_artist"
        )
    if acoustid_dist.get("below_0_5", 0) > 0:
        recommendations.append(
            f"{acoustid_dist['below_0_5']} track(s) have AcoustID score < 0.5 — potential mis-ID"
        )
    inconsistent = sum(1 for pr in per_record if not pr["album_consistent"])
    if inconsistent:
        recommendations.append(
            f"{inconsistent} record(s) have inconsistent album/album_artist across tracks"
        )
    if cross_agreement is not None and cross_agreement < 70:
        recommendations.append(
            f"Current pipeline and Shazam agree on album for only {cross_agreement}% of tracks"
        )
    if unmatched_albums:
        names = ", ".join(f"\"{ka['album']}\"" for ka in unmatched_albums[:3])
        tail = f" and {len(unmatched_albums) - 3} more" if len(unmatched_albums) > 3 else ""
        recommendations.append(f"Known albums not matched to any identified record: {names}{tail}")

    return {
        "summary": {
            "total_files": len(results),
            "total_records": len(per_record),
            "identified_by_current": identified,
            "identified_by_current_pct": round(identified / len(results) * 100, 1) if results else 0,
            "identified_by_shazam": shazam_identified,
            "records_matched_to_known": matched_records,
            "known_albums_provided": len(known_albums),
            "cross_source_agreement_pct": cross_agreement,
        },
        "field_coverage": {
            "current_pipeline": current_coverage,
            "shazam": shazam_coverage,
        },
        "acoustid_score_distribution": acoustid_dist,
        "per_record": per_record,
        "failure_modes": sorted(failures, key=lambda f: f["ipod_score"]),
        "recommendations": recommendations,
    }
