"""Tests for music_manager.identify — no real network calls are made."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from music_manager.track import Track
from music_manager.identify import fingerprint, identify, lookup_musicbrainz

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

FAKE_PATH = Path("/tmp/fake_song.m4a")
FAKE_API_KEY = "test-api-key"

# A realistic nested AcoustID result dict (as produced when
# meta="recordings releasegroups" is requested).
MOCK_RESULT_DICT = {
    "id": "acoustid-result-id",
    "score": 0.95,
    "recordings": [
        {
            "id": "mb-recording-uuid-1234",
            "title": "Paranoid Android",
            "artists": [{"id": "artist-uuid", "name": "Radiohead"}],
            "releases": [
                {
                    "id": "release-uuid",
                    "title": "OK Computer",
                    "date": "1997-05-28",
                    "mediums": [
                        {
                            "tracks": [
                                {"position": 2}
                            ]
                        }
                    ],
                }
            ],
        }
    ],
}


# ---------------------------------------------------------------------------
# fingerprint()
# ---------------------------------------------------------------------------


def test_fingerprint_calls_acoustid_fingerprint_file():
    """fingerprint() must delegate to acoustid.fingerprint_file with the path string."""
    fake_fp = b"AQAAAE..."

    with patch("music_manager.identify.acoustid.fingerprint_file", return_value=(240, fake_fp)) as mock_fp:
        result = fingerprint(FAKE_PATH)

    mock_fp.assert_called_once_with(str(FAKE_PATH))
    assert result == fake_fp


# ---------------------------------------------------------------------------
# lookup_musicbrainz()
# ---------------------------------------------------------------------------


def test_lookup_musicbrainz_parses_response():
    """lookup_musicbrainz() should parse a rich AcoustID dict into a Track."""
    with (
        patch("music_manager.identify.acoustid.match", return_value=iter([MOCK_RESULT_DICT])),
        patch("music_manager.identify.musicbrainzngs.set_useragent"),
    ):
        track = lookup_musicbrainz(FAKE_PATH, FAKE_API_KEY)

    assert track is not None
    assert track.path == FAKE_PATH
    assert track.title == "Paranoid Android"
    assert track.artist == "Radiohead"
    assert track.album == "OK Computer"
    assert track.year == "1997"
    assert track.track_number == 2
    assert track.musicbrainz_recording_id == "mb-recording-uuid-1234"
    # cover_art is Phase 3 — must be empty here
    assert track.cover_art == b""


def test_lookup_musicbrainz_returns_none_when_no_results():
    """lookup_musicbrainz() must return None when AcoustID finds nothing."""
    with (
        patch("music_manager.identify.acoustid.match", return_value=iter([])),
        patch("music_manager.identify.musicbrainzngs.set_useragent"),
    ):
        result = lookup_musicbrainz(FAKE_PATH, FAKE_API_KEY)

    assert result is None


def test_lookup_musicbrainz_returns_none_when_recordings_empty():
    """lookup_musicbrainz() must return None when the result has no recordings."""
    empty_recordings_result = {"id": "x", "score": 0.5, "recordings": []}

    with (
        patch("music_manager.identify.acoustid.match", return_value=iter([empty_recordings_result])),
        patch("music_manager.identify.musicbrainzngs.set_useragent"),
    ):
        result = lookup_musicbrainz(FAKE_PATH, FAKE_API_KEY)

    assert result is None


def test_lookup_musicbrainz_sets_useragent():
    """lookup_musicbrainz() must configure musicbrainzngs User-Agent before any request."""
    with (
        patch("music_manager.identify.acoustid.match", return_value=iter([MOCK_RESULT_DICT])),
        patch("music_manager.identify.musicbrainzngs.set_useragent") as mock_ua,
    ):
        lookup_musicbrainz(FAKE_PATH, FAKE_API_KEY)

    mock_ua.assert_called_once_with("music-library-manager", "0.1", "https://github.com/caique-lima/music-library-manager")


# ---------------------------------------------------------------------------
# identify()
# ---------------------------------------------------------------------------


def test_identify_returns_track_on_match():
    """identify() should propagate the Track returned by lookup_musicbrainz."""
    expected = Track(
        path=FAKE_PATH,
        title="Paranoid Android",
        artist="Radiohead",
        album="OK Computer",
        year="1997",
        track_number=2,
        musicbrainz_recording_id="mb-recording-uuid-1234",
    )

    with patch("music_manager.identify.lookup_musicbrainz", return_value=expected):
        result = identify(FAKE_PATH, FAKE_API_KEY)

    assert result == expected


def test_identify_returns_empty_track_when_no_match():
    """identify() must return an empty Track when both AcoustID and Shazam find nothing."""
    with patch("music_manager.identify.lookup_musicbrainz", return_value=None):
        with patch("music_manager.identify.identify_shazam", return_value=None):
            result = identify(FAKE_PATH, FAKE_API_KEY)

    assert result.path == FAKE_PATH
    assert result.title == ""
    assert result.artist == ""
    assert result.album == ""
    assert result.year == ""
    assert result.track_number == 0
    assert result.musicbrainz_recording_id == ""
    assert result.cover_art == b""
