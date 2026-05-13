from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from music_manager.stems import stem_output_dir, separate_stems


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _patch_mp4(tags):
    """Context manager: make MP4(...).tags return *tags*."""
    mock_audio = MagicMock()
    mock_audio.tags = tags
    return patch("music_manager.stems.MP4", return_value=mock_audio)


# ---------------------------------------------------------------------------
# stem_output_dir
# ---------------------------------------------------------------------------

class TestStemOutputDir:
    def test_fully_populated(self, tmp_path):
        track = tmp_path / "track.m4a"
        track.touch()
        tags = {
            "\xa9nam": ["Song Title"],
            "aART": ["Album Artist"],
            "\xa9alb": ["My Album"],
            "\xa9day": ["2023"],
        }
        with _patch_mp4(tags):
            out = stem_output_dir(track, tmp_path)
        assert out == tmp_path / "stems" / "Album Artist" / "My Album (2023)" / "Song Title"

    def test_falls_back_to_track_artist_when_no_album_artist(self, tmp_path):
        track = tmp_path / "track.m4a"
        track.touch()
        tags = {
            "\xa9nam": ["Song"],
            "\xa9ART": ["Track Artist"],
            "\xa9alb": ["Album"],
            "\xa9day": ["2020"],
        }
        with _patch_mp4(tags):
            out = stem_output_dir(track, tmp_path)
        assert out == tmp_path / "stems" / "Track Artist" / "Album (2020)" / "Song"

    def test_no_year_omits_parentheses(self, tmp_path):
        track = tmp_path / "track.m4a"
        track.touch()
        tags = {
            "\xa9nam": ["Song"],
            "aART": ["Artist"],
            "\xa9alb": ["Album"],
        }
        with _patch_mp4(tags):
            out = stem_output_dir(track, tmp_path)
        assert out == tmp_path / "stems" / "Artist" / "Album" / "Song"

    def test_no_metadata_falls_back_to_defaults(self, tmp_path):
        track = tmp_path / "my_track.m4a"
        track.touch()
        with _patch_mp4(None):
            out = stem_output_dir(track, tmp_path)
        assert out == tmp_path / "stems" / "Unknown Artist" / "Unknown Album" / "my_track"

    def test_sanitizes_slashes_in_components(self, tmp_path):
        track = tmp_path / "track.m4a"
        track.touch()
        tags = {
            "\xa9nam": ["Song/Title"],
            "aART": ["Artist/Name"],
            "\xa9alb": ["Album/Name"],
            "\xa9day": ["2021"],
        }
        with _patch_mp4(tags):
            out = stem_output_dir(track, tmp_path)
        assert out == tmp_path / "stems" / "Artist-Name" / "Album-Name (2021)" / "Song-Title"

    def test_year_truncated_to_four_chars(self, tmp_path):
        track = tmp_path / "track.m4a"
        track.touch()
        tags = {
            "\xa9nam": ["Song"],
            "aART": ["Artist"],
            "\xa9alb": ["Album"],
            "\xa9day": ["2023-05-12"],
        }
        with _patch_mp4(tags):
            out = stem_output_dir(track, tmp_path)
        assert out == tmp_path / "stems" / "Artist" / "Album (2023)" / "Song"


# ---------------------------------------------------------------------------
# separate_stems
# ---------------------------------------------------------------------------

class TestSeparateStems:
    def test_dry_run_returns_dir_without_writing(self, tmp_path):
        track = tmp_path / "track.m4a"
        track.touch()
        tags = {
            "\xa9nam": ["Song"],
            "aART": ["Artist"],
            "\xa9alb": ["Album"],
            "\xa9day": ["2023"],
        }
        with _patch_mp4(tags):
            out = separate_stems(track, tmp_path, dry_run=True)
        assert out == tmp_path / "stems" / "Artist" / "Album (2023)" / "Song"
        assert not (tmp_path / "stems").exists()

    def test_calls_run_demucs_with_correct_paths(self, tmp_path):
        track = tmp_path / "track.m4a"
        track.touch()
        tags = {
            "\xa9nam": ["Song"],
            "aART": ["Artist"],
            "\xa9alb": ["Album"],
            "\xa9day": ["2023"],
        }
        expected_out = tmp_path / "stems" / "Artist" / "Album (2023)" / "Song"
        with _patch_mp4(tags), patch("music_manager.stems._run_demucs") as mock_run:
            out = separate_stems(track, tmp_path)
        mock_run.assert_called_once_with(track, expected_out)
        assert out == expected_out

    def test_raises_runtime_error_when_demucs_missing(self, tmp_path):
        track = tmp_path / "track.m4a"
        track.touch()
        with _patch_mp4({}), \
             patch("music_manager.stems._run_demucs", side_effect=ImportError("no demucs")):
            with pytest.raises(RuntimeError, match="demucs is not installed"):
                separate_stems(track, tmp_path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

class TestStemsCli:
    @pytest.fixture(autouse=True)
    def _cli(self):
        from music_manager.cli import cli as _cli
        self.cli = _cli

    def test_single_file_dry_run(self, tmp_path):
        track = tmp_path / "track.m4a"
        track.touch()
        runner = CliRunner()
        tags = {
            "\xa9nam": ["Song"],
            "aART": ["Artist"],
            "\xa9alb": ["Album"],
            "\xa9day": ["2023"],
        }
        with _patch_mp4(tags):
            result = runner.invoke(self.cli, ["stems", str(track), "--dry-run"])
        assert result.exit_code == 0
        assert "1 separated" in result.output
        assert not (tmp_path / "stems").exists()

    def test_directory_with_no_m4a_files(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(self.cli, ["stems", str(tmp_path)])
        assert result.exit_code == 0
        assert "No M4A files found" in result.output

    def test_directory_processes_all_m4a_files(self, tmp_path):
        for name in ("a.m4a", "b.m4a"):
            (tmp_path / name).touch()
        runner = CliRunner()
        tags = {"\xa9nam": ["Song"], "aART": ["Artist"], "\xa9alb": ["Album"], "\xa9day": ["2023"]}
        with _patch_mp4(tags), patch("music_manager.stems._run_demucs"):
            result = runner.invoke(self.cli, ["stems", str(tmp_path), "--dry-run"])
        assert result.exit_code == 0
        assert "2 separated" in result.output

    def test_demucs_error_is_reported_per_track(self, tmp_path):
        track = tmp_path / "track.m4a"
        track.touch()
        runner = CliRunner()
        with _patch_mp4({}), \
             patch("music_manager.stems._run_demucs", side_effect=ImportError("no demucs")):
            result = runner.invoke(self.cli, ["stems", str(track)])
        assert result.exit_code == 0
        assert "demucs is not installed" in result.output
        assert "errors" in result.output
