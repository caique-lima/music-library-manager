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
