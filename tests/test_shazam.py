from pathlib import Path
from unittest.mock import patch, MagicMock

from music_manager.shazam import identify_shazam, _parse

FAKE_PATH = Path("/tmp/fake.m4a")

MOCK_RESPONSE = {
    "matches": [{"id": "211988224"}],
    "track": {
        "title": "Xtal",
        "subtitle": "Aphex Twin",
        "genres": {"primary": "Electronic"},
        "images": {"coverart": "https://example.com/cover.jpg"},
        "sections": [
            {
                "type": "SONG",
                "metadata": [
                    {"title": "Album", "text": "Selected Ambient Works 85-92"},
                    {"title": "Label", "text": "R&S Records"},
                    {"title": "Released", "text": "1992"},
                ],
            }
        ],
    },
}


def test_parse_populates_track():
    track = _parse(MOCK_RESPONSE, FAKE_PATH)
    assert track is not None
    assert track.title == "Xtal"
    assert track.artist == "Aphex Twin"
    assert track.album == "Selected Ambient Works 85-92"
    assert track.year == "1992"
    assert track.genre == "Electronic"
    assert track.path == FAKE_PATH


def test_parse_returns_none_on_no_match():
    assert _parse({}, FAKE_PATH) is None
    assert _parse({"matches": []}, FAKE_PATH) is None


def test_parse_fetches_cover_art():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b"fake-image-bytes"

    with patch("music_manager.shazam.requests.get", return_value=mock_resp):
        track = _parse(MOCK_RESPONSE, FAKE_PATH)

    assert track.cover_art == b"fake-image-bytes"


def test_parse_skips_cover_art_on_failure():
    with patch("music_manager.shazam.requests.get", side_effect=Exception("timeout")):
        track = _parse(MOCK_RESPONSE, FAKE_PATH)

    assert track.cover_art == b""


def test_parse_handles_missing_metadata_gracefully():
    minimal = {
        "track": {
            "title": "Some Track",
            "subtitle": "Some Artist",
        }
    }
    track = _parse(minimal, FAKE_PATH)
    assert track.title == "Some Track"
    assert track.album == ""
    assert track.year == ""
    assert track.genre == ""


def test_identify_shazam_returns_track(tmp_path):
    fake_file = tmp_path / "track.m4a"
    fake_file.touch()

    with patch("music_manager.shazam.asyncio.run", return_value=MOCK_RESPONSE):
        with patch("music_manager.shazam.requests.get") as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.content = b"img"
            track = identify_shazam(fake_file)

    assert track is not None
    assert track.title == "Xtal"


def test_identify_shazam_returns_none_on_no_match(tmp_path):
    fake_file = tmp_path / "track.m4a"
    fake_file.touch()

    with patch("music_manager.shazam.asyncio.run", return_value={}):
        track = identify_shazam(fake_file)

    assert track is None
