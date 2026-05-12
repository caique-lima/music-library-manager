import pytest
from pathlib import Path
from unittest.mock import patch, call

from music_manager.convert import wav_to_alac, convert_directory


def test_wav_to_alac_calls_ffmpeg(tmp_path):
    src = tmp_path / "track.wav"
    src.touch()
    dest = tmp_path / "track.m4a"

    with patch("music_manager.convert.ffmpeg") as mock_ffmpeg:
        mock_run = mock_ffmpeg.input.return_value.output.return_value.overwrite_output.return_value
        wav_to_alac(src, dest)

    mock_ffmpeg.input.assert_called_once_with(str(src))
    mock_ffmpeg.input.return_value.output.assert_called_once_with(
        str(dest), acodec="alac", loglevel="error"
    )
    mock_run.run.assert_called_once()


def test_wav_to_alac_creates_parent_dirs(tmp_path):
    src = tmp_path / "track.wav"
    src.touch()
    dest = tmp_path / "nested" / "dir" / "track.m4a"

    with patch("music_manager.convert.ffmpeg"):
        wav_to_alac(src, dest)

    assert dest.parent.exists()


def test_wav_to_alac_returns_dest(tmp_path):
    src = tmp_path / "track.wav"
    src.touch()
    dest = tmp_path / "track.m4a"

    with patch("music_manager.convert.ffmpeg"):
        result = wav_to_alac(src, dest)

    assert result == dest


def test_convert_directory_finds_wavs(tmp_path):
    (tmp_path / "a.wav").touch()
    (tmp_path / "b.wav").touch()
    (tmp_path / "c.mp3").touch()

    with patch("music_manager.convert.wav_to_alac") as mock_convert:
        pairs = convert_directory(tmp_path)

    assert len(pairs) == 2
    assert all(dest.suffix == ".m4a" for _, dest in pairs)
    assert mock_convert.call_count == 2


def test_convert_directory_dry_run_skips_conversion(tmp_path):
    (tmp_path / "a.wav").touch()

    with patch("music_manager.convert.wav_to_alac") as mock_convert:
        pairs = convert_directory(tmp_path, dry_run=True)

    assert len(pairs) == 1
    mock_convert.assert_not_called()


def test_convert_directory_empty(tmp_path):
    pairs = convert_directory(tmp_path)
    assert pairs == []
