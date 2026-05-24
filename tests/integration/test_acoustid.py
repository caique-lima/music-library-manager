"""Live AcoustID/MusicBrainz integration tests.

Each test injects a stored chromaprint fingerprint so no audio file is needed,
then lets the full pipeline hit the real AcoustID, MusicBrainz, and iTunes APIs.
Shazam is suppressed — these tests exercise the AcoustID path only.

Run with:
    ACOUSTID_API_KEY=<key> uv run pytest tests/integration/ -m integration -v -s

Override the accuracy threshold:
    ACOUSTID_ACCURACY_THRESHOLD=0.90 ACOUSTID_API_KEY=<key> uv run pytest tests/integration/ -m integration -v -s
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from music_manager.benchmark import _field_match
from music_manager.identify import identify

_FIXTURES_PATH = Path(__file__).parent / "fixtures" / "fingerprints.json"
_FIXTURES = json.loads(_FIXTURES_PATH.read_text())


def _run_fixture(fx: dict, api_key: str) -> "Track":
    """Identify a fixture track using a stored fingerprint (no audio file needed)."""
    from music_manager.track import Track

    duration_s = fx["duration_ms"] / 1000
    fingerprint_bytes = fx["fingerprint"].encode("utf-8")
    dur_ms = fx["duration_ms"]

    def _fake_duration_diff(path, recording):
        mb_ms = int(recording.get("length") or 0)
        if not mb_ms:
            return 30
        return abs(dur_ms - mb_ms) // 1000

    with (
        patch("acoustid.fingerprint_file", return_value=(duration_s, fingerprint_bytes)),
        patch("music_manager.shazam.identify_via_shazam", return_value=None),
        patch("music_manager.identify._duration_diff_s", side_effect=_fake_duration_diff),
    ):
        return identify(
            Path(f"/tmp/integration_{fx['name']}.m4a"),
            acoustid_api_key=api_key,
        )


def _field_checks(track, exp: dict) -> list[tuple[str, bool, str, str]]:
    """Return (field, passed, got, expected) tuples for every asserted field."""
    checks = []
    for field in ("title", "artist", "album"):
        got = getattr(track, field, "")
        want = exp[field]
        ok = bool(got) and _field_match(got, want)
        checks.append((field, ok, got, want))
    if exp.get("year"):
        got = getattr(track, "year", "")
        want = exp["year"]
        ok = bool(got) and got[:4] == want[:4]
        checks.append(("year", ok, got, want))
    if exp.get("album_artist"):
        got = getattr(track, "album_artist", "")
        want = exp["album_artist"]
        ok = bool(got) and _field_match(got, want)
        checks.append(("album_artist", ok, got, want))
    return checks


@pytest.mark.integration
def test_identify_acoustid_accuracy(acoustid_api_key, acoustid_accuracy_threshold):
    """AcoustID identification accuracy across all stored fingerprint fixtures.

    Passes when the fraction of correct field identifications meets or exceeds
    the configured threshold (``tool.music-manager.integration_accuracy_threshold``
    in pyproject.toml, or ``ACOUSTID_ACCURACY_THRESHOLD`` env var).
    """
    total = 0
    passed = 0
    rows = []

    for fx in _FIXTURES:
        track = _run_fixture(fx, acoustid_api_key)
        checks = _field_checks(track, fx["expected"])
        fx_pass = sum(1 for _, ok, _, _ in checks if ok)
        fx_total = len(checks)
        total += fx_total
        passed += fx_pass
        rows.append((fx["name"], fx_pass, fx_total, checks))

    accuracy = passed / total if total else 0.0

    # Always print results table (visible with -s or on failure)
    print(f"\n{'fixture':<42} {'score':>7}  failures")
    print("-" * 72)
    for name, fp, ft, checks in rows:
        mark = "✓" if fp == ft else "✗"
        fails = ", ".join(
            f"{f}={got!r}≠{want!r}"
            for f, ok, got, want in checks
            if not ok
        )
        print(f"  {mark} {name:<40} {fp}/{ft}  {fails}")
    print("-" * 72)
    print(f"  accuracy: {passed}/{total} = {accuracy:.1%}   threshold: {acoustid_accuracy_threshold:.1%}\n")

    assert accuracy >= acoustid_accuracy_threshold, (
        f"AcoustID accuracy {accuracy:.1%} ({passed}/{total}) is below "
        f"threshold {acoustid_accuracy_threshold:.1%} — run with -s to see full breakdown"
    )
