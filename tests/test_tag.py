import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from mutagen.mp4 import MP4

from music_manager.tag import fetch_cover_art, tag_track, write_tags
from music_manager.track import Track


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_test_m4a(path: Path) -> Path:
    """Generate a minimal ALAC .m4a file using ffmpeg."""
    subprocess.run(
        [
            "ffmpeg",
            "-f", "lavfi",
            "-i", "sine=frequency=440:duration=1",
            "-c:a", "alac",
            str(path),
            "-y",
        ],
        check=True,
        capture_output=True,
    )
    return path


FAKE_JPEG = b"\xff\xd8\xff" + b"\x00" * 10  # minimal fake JPEG bytes


# ---------------------------------------------------------------------------
# fetch_cover_art tests
# ---------------------------------------------------------------------------

class TestFetchCoverArt:
    def test_returns_bytes_on_success(self):
        with patch("music_manager.tag.fetch_url", return_value=FAKE_JPEG) as mock_fetch:
            result = fetch_cover_art("some-recording-id")
        mock_fetch.assert_called_once_with(
            "https://coverartarchive.org/recording/some-recording-id/front"
        )
        assert result == FAKE_JPEG

    def test_returns_empty_bytes_on_failure(self):
        with patch("music_manager.tag.fetch_url", return_value=b""):
            assert fetch_cover_art("missing-id") == b""


# ---------------------------------------------------------------------------
# write_tags tests
# ---------------------------------------------------------------------------

class TestWriteTags:
    def test_writes_all_tags(self, tmp_path):
        m4a_path = make_test_m4a(tmp_path / "track.m4a")
        track = Track(
            path=m4a_path,
            title="My Song",
            artist="My Artist",
            album="My Album",
            year="2024",
            genre="Rock",
            track_number=3,
        )

        write_tags(track)

        audio = MP4(str(m4a_path))
        assert audio["\xa9nam"] == ["My Song"]
        assert audio["\xa9ART"] == ["My Artist"]
        assert audio["\xa9alb"] == ["My Album"]
        assert audio["\xa9day"] == ["2024"]
        assert audio["\xa9gen"] == ["Rock"]
        assert audio["trkn"] == [(3, 0)]

    def test_skips_empty_string_tags(self, tmp_path):
        m4a_path = make_test_m4a(tmp_path / "track.m4a")
        track = Track(path=m4a_path, title="Only Title")

        write_tags(track)

        audio = MP4(str(m4a_path))
        assert audio.get("\xa9nam") == ["Only Title"]
        assert "\xa9ART" not in audio
        assert "\xa9alb" not in audio
        assert "\xa9day" not in audio
        assert "\xa9gen" not in audio
        assert "trkn" not in audio

    def test_skips_cover_art_when_empty(self, tmp_path):
        m4a_path = make_test_m4a(tmp_path / "track.m4a")
        track = Track(path=m4a_path, title="No Cover")

        write_tags(track)

        audio = MP4(str(m4a_path))
        assert "covr" not in audio

    def test_embeds_cover_art_when_present(self, tmp_path):
        m4a_path = make_test_m4a(tmp_path / "track.m4a")
        track = Track(path=m4a_path, title="With Cover", cover_art=FAKE_JPEG)

        write_tags(track)

        audio = MP4(str(m4a_path))
        assert "covr" in audio
        covers = audio["covr"]
        assert len(covers) == 1
        assert bytes(covers[0]) == FAKE_JPEG

    def test_skips_zero_track_number(self, tmp_path):
        m4a_path = make_test_m4a(tmp_path / "track.m4a")
        track = Track(path=m4a_path, title="Track Zero", track_number=0)

        write_tags(track)

        audio = MP4(str(m4a_path))
        assert "trkn" not in audio


# ---------------------------------------------------------------------------
# tag_track tests
# ---------------------------------------------------------------------------

class TestTagTrack:
    def test_calls_fetch_cover_art_when_recording_id_set_and_cover_art_empty(self, tmp_path):
        m4a_path = make_test_m4a(tmp_path / "track.m4a")
        track = Track(
            path=m4a_path,
            title="Test",
            musicbrainz_recording_id="abc-123",
        )

        with patch("music_manager.tag.fetch_cover_art", return_value=FAKE_JPEG) as mock_fetch:
            tag_track(track)

        mock_fetch.assert_called_once_with("abc-123")
        assert track.cover_art == FAKE_JPEG

    def test_skips_fetch_cover_art_when_cover_art_already_set(self, tmp_path):
        m4a_path = make_test_m4a(tmp_path / "track.m4a")
        track = Track(
            path=m4a_path,
            title="Test",
            musicbrainz_recording_id="abc-123",
            cover_art=FAKE_JPEG,
        )

        with patch("music_manager.tag.fetch_cover_art") as mock_fetch:
            tag_track(track)

        mock_fetch.assert_not_called()

    def test_skips_fetch_cover_art_when_no_recording_id(self, tmp_path):
        m4a_path = make_test_m4a(tmp_path / "track.m4a")
        track = Track(path=m4a_path, title="No ID")

        with patch("music_manager.tag.fetch_cover_art") as mock_fetch:
            tag_track(track)

        mock_fetch.assert_not_called()

    def test_calls_write_tags(self, tmp_path):
        m4a_path = make_test_m4a(tmp_path / "track.m4a")
        track = Track(path=m4a_path, title="Write Test")

        with patch("music_manager.tag.write_tags") as mock_write:
            tag_track(track)

        mock_write.assert_called_once_with(track)
