"""Live Shazam integration tests.

Uses short CC-BY audio clips stored in fixtures/audio/ — no personal music
files needed. Each clip is sent to the real Shazam API via shazamio.

Run with:
    uv run pytest tests/integration/ -m integration -v -s

Override the accuracy threshold:
    SHAZAM_ACCURACY_THRESHOLD=0.90 uv run pytest tests/integration/ -m integration -v -s
"""

import json
from pathlib import Path

import pytest

from music_manager.benchmark import _field_match
from music_manager.identify import identify
from music_manager.shazam import identify_via_shazam

_FIXTURES_PATH = Path(__file__).parent / "fixtures" / "shazam_fixtures.json"
_FIXTURES = json.loads(_FIXTURES_PATH.read_text())
_AUDIO_ROOT = _FIXTURES_PATH.parent


def _field_checks(track, exp: dict) -> list[tuple[str, bool, str, str]]:
    checks = []
    for field in ("title", "artist"):
        got = getattr(track, field, "") if track else ""
        want = exp[field]
        ok = bool(got) and _field_match(got, want)
        checks.append((field, ok, got, want))
    if exp.get("album") and track:
        got = track.album
        want = exp["album"]
        checks.append(("album", bool(got) and _field_match(got, want), got, want))
    return checks


@pytest.mark.integration
def test_identify_shazam_fallback_pipeline():
    """identify() with no AcoustID key must produce a fully-populated Track via Shazam.

    Exercises the path: identify() → identify_via_shazam() → iTunes lookup → cover art fetch.
    Verifies the structural guarantees that identify() is responsible for (album_artist always
    set, cover_art populated) in addition to the basic title/artist accuracy.
    """
    audio_path = _AUDIO_ROOT / "audio/kevin_macleod_sneaky_snitch.m4a"

    track = identify(audio_path)  # no acoustid_api_key → Shazam is primary

    assert track.title, "title must be populated"
    assert _field_match(track.title, "Sneaky Snitch"), f"title: {track.title!r}"
    assert _field_match(track.artist, "Kevin MacLeod"), f"artist: {track.artist!r}"

    # Structural guarantees that identify() is responsible for:
    assert track.album_artist, (
        "album_artist must always be set by identify() — used for folder grouping on iPod"
    )
    assert track.cover_art, "cover_art must be fetched (Shazam provides artwork URL)"


@pytest.mark.integration
def test_identify_shazam_accuracy(shazam_accuracy_threshold):
    """Shazam identification accuracy across all stored audio fixtures.

    Passes when the fraction of correct field identifications meets or exceeds
    the configured threshold (``tool.music-manager.shazam_accuracy_threshold``
    in pyproject.toml, or ``SHAZAM_ACCURACY_THRESHOLD`` env var).
    """
    total = 0
    passed = 0
    rows = []

    for fx in _FIXTURES:
        audio_path = _AUDIO_ROOT / fx["audio_file"]
        track = identify_via_shazam(audio_path)
        checks = _field_checks(track, fx["expected"])
        fx_pass = sum(1 for _, ok, _, _ in checks if ok)
        fx_total = len(checks)
        total += fx_total
        passed += fx_pass
        rows.append((fx["name"], fx_pass, fx_total, checks))

    accuracy = passed / total if total else 0.0

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
    print(f"  accuracy: {passed}/{total} = {accuracy:.1%}   threshold: {shazam_accuracy_threshold:.1%}\n")

    assert accuracy >= shazam_accuracy_threshold, (
        f"Shazam accuracy {accuracy:.1%} ({passed}/{total}) is below "
        f"threshold {shazam_accuracy_threshold:.1%} — run with -s to see full breakdown"
    )
