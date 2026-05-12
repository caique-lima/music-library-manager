from pathlib import Path
from unittest.mock import patch, MagicMock
from click.testing import CliRunner

from music_manager.cli import cli
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


def test_process_no_wavs(tmp_path):
    runner = CliRunner()
    result = runner.invoke(cli, ["process", str(tmp_path), "--api-key", FAKE_API_KEY])
    assert result.exit_code == 0
    assert "No WAV files found" in result.output


def test_process_dry_run(tmp_path):
    (tmp_path / "track.wav").touch()
    runner = CliRunner()
    result = runner.invoke(cli, ["process", str(tmp_path), "--dry-run", "--api-key", FAKE_API_KEY])
    assert result.exit_code == 0
    assert "would convert" in result.output


def test_process_full_pipeline(tmp_path):
    wav = tmp_path / "track.wav"
    wav.touch()
    alac = tmp_path / "track.m4a"
    dest = tmp_path / "Radiohead" / "OK Computer (1997)" / "02 Paranoid Android.m4a"

    runner = CliRunner()
    with (
        patch("music_manager.cli.convert_directory", return_value=[(wav, alac)]),
        patch("music_manager.cli.identify", return_value=_fake_track(alac)),
        patch("music_manager.cli.tag_track"),
        patch("music_manager.cli.move_track", return_value=dest),
        patch("music_manager.cli.delete_original_wav"),
    ):
        result = runner.invoke(cli, ["process", str(tmp_path), "--api-key", FAKE_API_KEY])

    assert result.exit_code == 0
    assert "Radiohead" in result.output
    assert "Paranoid Android" in result.output
    assert "1 organized" in result.output


def test_process_no_match_skips(tmp_path):
    wav = tmp_path / "track.wav"
    wav.touch()
    alac = tmp_path / "track.m4a"
    empty_track = Track(path=alac)

    runner = CliRunner()
    with (
        patch("music_manager.cli.convert_directory", return_value=[(wav, alac)]),
        patch("music_manager.cli.identify", return_value=empty_track),
    ):
        result = runner.invoke(cli, ["process", str(tmp_path), "--api-key", FAKE_API_KEY])

    assert result.exit_code == 0
    assert "no match found" in result.output
    assert "0 organized, 1 skipped" in result.output


def test_process_reads_api_key_from_env(tmp_path):
    runner = CliRunner()
    result = runner.invoke(
        cli, ["process", str(tmp_path)],
        env={"ACOUSTID_API_KEY": FAKE_API_KEY},
    )
    assert result.exit_code == 0
    assert "No WAV files found" in result.output
