from pathlib import Path
from unittest.mock import patch, MagicMock
from click.testing import CliRunner

from music_manager.cli import cli, _process_track, _TrackResult
from music_manager.track import Track

FAKE_API_KEY = "test-key"


def _fake_track(alac_path: Path) -> Track:
    return Track(
        path=alac_path,
        artist="Radiohead",
        album="OK Computer",
        year="1997",
        title="Paranoid Android",
        track_number=2,
        musicbrainz_recording_id="mb-id",
    )


# --- _process_track unit tests ---

def test_process_track_ok(tmp_path):
    wav = tmp_path / "track.wav"
    wav.touch()
    alac = tmp_path / "track.m4a"
    alac.touch()
    dest = tmp_path / "Radiohead" / "OK Computer (1997)" / "02 Paranoid Android.m4a"

    with (
        patch("music_manager.cli.wav_to_alac"),
        patch("music_manager.cli.identify", return_value=_fake_track(alac)),
        patch("music_manager.cli.tag_track"),
        patch("music_manager.cli.move_track", return_value=dest),
        patch("music_manager.cli.delete_original_wav"),
    ):
        result = _process_track(wav, FAKE_API_KEY, tmp_path)

    assert result.status == "ok"
    assert result.dest == dest
    assert "Radiohead" in result.label


def test_process_track_no_match(tmp_path):
    wav = tmp_path / "track.wav"
    wav.touch()
    alac = tmp_path / "track.m4a"
    alac.touch()

    with (
        patch("music_manager.cli.wav_to_alac"),
        patch("music_manager.cli.identify", return_value=Track(path=alac)),
    ):
        result = _process_track(wav, FAKE_API_KEY, tmp_path)

    assert result.status == "skipped"


def test_process_track_acoustid_error(tmp_path):
    import acoustid
    wav = tmp_path / "track.wav"
    wav.touch()

    with (
        patch("music_manager.cli.wav_to_alac"),
        patch("music_manager.cli.identify", side_effect=acoustid.WebServiceError("503")),
    ):
        result = _process_track(wav, FAKE_API_KEY, tmp_path)

    assert result.status == "error"


# --- CLI integration tests ---

def test_process_no_wavs(tmp_path):
    runner = CliRunner()
    result = runner.invoke(cli, ["process", str(tmp_path)])
    assert result.exit_code == 0
    assert "No WAV files found" in result.output


def test_process_dry_run(tmp_path):
    (tmp_path / "track.wav").touch()
    runner = CliRunner()
    result = runner.invoke(cli, ["process", str(tmp_path), "--dry-run"])
    assert result.exit_code == 0
    assert "would process" in result.output


def test_process_concurrent(tmp_path):
    (tmp_path / "a.wav").touch()
    (tmp_path / "b.wav").touch()
    dest = tmp_path / "Radiohead" / "OK Computer (1997)" / "02 Paranoid Android.m4a"

    def fake_process(wav, api_key, library_root):
        return _TrackResult(src=wav, status="ok", dest=dest, label="Radiohead — Paranoid Android (1997)")

    runner = CliRunner()
    with patch("music_manager.cli._process_track", side_effect=fake_process):
        result = runner.invoke(cli, ["process", str(tmp_path), "--workers", "2"])

    assert result.exit_code == 0
    assert "2 organized" in result.output


def test_process_reports_skipped_and_errors(tmp_path):
    (tmp_path / "a.wav").touch()
    (tmp_path / "b.wav").touch()

    results = [
        _TrackResult(src=tmp_path / "a.wav", status="skipped", label="no match found"),
        _TrackResult(src=tmp_path / "b.wav", status="error", label="503"),
    ]

    runner = CliRunner()
    with patch("music_manager.cli._process_track", side_effect=results):
        result = runner.invoke(cli, ["process", str(tmp_path)])

    assert "1 skipped" in result.output
    assert "1 errors" in result.output
