from pathlib import Path
from unittest.mock import patch, MagicMock

from music_manager.shazam import identify_shazam, _parse, _apple_music_id, _apple_music_track_number

FAKE_PATH = Path("/tmp/fake.m4a")

MOCK_RESPONSE = {
    "matches": [{"id": "211988224"}],
    "track": {
        "title": "Xtal",
        "subtitle": "Aphex Twin",
        "genres": {"primary": "Electronic"},
        "images": {"coverart": "https://example.com/cover.jpg"},
        "hub": {
            "actions": [
                {"name": "apple", "type": "applemusicplay", "id": "1668862649"},
                {"name": "apple", "type": "uri", "uri": "https://audio-ssl.itunes.apple.com/..."},
            ]
        },
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


def test_apple_music_id_extracts_id():
    assert _apple_music_id(MOCK_RESPONSE["track"]) == "1668862649"


def test_apple_music_id_returns_empty_when_missing():
    assert _apple_music_id({}) == ""
    assert _apple_music_id({"hub": {"actions": [{"type": "uri"}]}}) == ""


def test_apple_music_track_number_parses_response():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"results": [{"trackNumber": 3}]}

    with patch("music_manager.shazam.requests.get", return_value=mock_resp):
        assert _apple_music_track_number("123") == 3


def test_apple_music_track_number_returns_zero_on_failure():
    with patch("music_manager.shazam.requests.get", side_effect=Exception("timeout")):
        assert _apple_music_track_number("123") == 0


def test_parse_populates_track():
    mock_itunes = MagicMock()
    mock_itunes.status_code = 200
    mock_itunes.json.return_value = {"results": [{"trackNumber": 1}]}

    with patch("music_manager.shazam.requests.get", return_value=mock_itunes):
        track = _parse(MOCK_RESPONSE, FAKE_PATH)

    assert track is not None
    assert track.title == "Xtal"
    assert track.artist == "Aphex Twin"
    assert track.album == "Selected Ambient Works 85-92"
    assert track.year == "1992"
    assert track.genre == "Electronic"
    assert track.track_number == 1
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
