from pathlib import Path

import pytest

from music_manager.organize import delete_original_wav, destination_path, move_track
from music_manager.track import Track


def make_track(tmp_path: Path, filename: str = "song.m4a", **kwargs) -> Track:
    """Create a Track whose path exists on disk."""
    path = tmp_path / filename
    path.touch()
    defaults = dict(
        artist="The Beatles",
        album="Abbey Road",
        year="1969",
        title="Come Together",
        track_number=1,
    )
    defaults.update(kwargs)
    return Track(path=path, **defaults)


# ---------------------------------------------------------------------------
# destination_path
# ---------------------------------------------------------------------------


def test_destination_path_fully_populated(tmp_path):
    track = make_track(tmp_path, track_number=3, title="Something")
    dest = destination_path(track, tmp_path / "lib")
    assert dest == tmp_path / "lib" / "The Beatles" / "Abbey Road (1969)" / "03 Something.m4a"


def test_destination_path_uses_album_artist_for_folder(tmp_path):
    track = make_track(tmp_path, artist="Dr. Dre, Charis Henry & Mel-Man", album_artist="Dr. Dre")
    dest = destination_path(track, tmp_path / "lib")
    assert dest.parts[-3] == "Dr. Dre"


def test_destination_path_falls_back_to_artist_when_no_album_artist(tmp_path):
    track = make_track(tmp_path, artist="Aphex Twin", album_artist="")
    dest = destination_path(track, tmp_path / "lib")
    assert dest.parts[-3] == "Aphex Twin"


def test_destination_path_track_number_zero(tmp_path):
    track = make_track(tmp_path, track_number=0, title="Something")
    dest = destination_path(track, tmp_path / "lib")
    # No numeric prefix when track_number is 0
    assert dest == tmp_path / "lib" / "The Beatles" / "Abbey Road (1969)" / "Something.m4a"


def test_destination_path_empty_artist_album_year(tmp_path):
    track = Track(
        path=tmp_path / "song.m4a",
        artist="",
        album="",
        year="",
        title="My Song",
        track_number=1,
    )
    dest = destination_path(track, tmp_path / "lib")
    assert dest == tmp_path / "lib" / "Unknown Artist" / "Unknown Album" / "01 My Song.m4a"


def test_destination_path_empty_title_uses_stem(tmp_path):
    track = Track(
        path=tmp_path / "original_stem.m4a",
        artist="Artist",
        album="Album",
        year="2000",
        title="",
        track_number=2,
    )
    dest = destination_path(track, tmp_path / "lib")
    assert dest == tmp_path / "lib" / "Artist" / "Album (2000)" / "02 original_stem.m4a"


def test_destination_path_no_year_suffix(tmp_path):
    track = make_track(tmp_path, year="", title="Song")
    dest = destination_path(track, tmp_path / "lib")
    # Album folder should not have a year suffix
    assert dest == tmp_path / "lib" / "The Beatles" / "Abbey Road" / "01 Song.m4a"


def test_destination_path_sanitizes_slashes(tmp_path):
    track = Track(
        path=tmp_path / "song.m4a",
        artist="AC/DC",
        album="Highway/To Hell",
        year="1979",
        title="Touch/Too Much",
        track_number=5,
    )
    dest = destination_path(track, tmp_path / "lib")
    assert dest == tmp_path / "lib" / "AC-DC" / "Highway-To Hell (1979)" / "05 Touch-Too Much.m4a"


def test_destination_path_strips_whitespace(tmp_path):
    track = Track(
        path=tmp_path / "song.m4a",
        artist="  Led Zeppelin  ",
        album="  IV  ",
        year="  1971  ",
        title="  Black Dog  ",
        track_number=1,
    )
    dest = destination_path(track, tmp_path / "lib")
    assert dest == tmp_path / "lib" / "Led Zeppelin" / "IV (1971)" / "01 Black Dog.m4a"


def test_destination_path_track_number_zero_padded(tmp_path):
    track = make_track(tmp_path, track_number=9, title="Track Nine")
    dest = destination_path(track, tmp_path / "lib")
    assert dest.name == "09 Track Nine.m4a"


# ---------------------------------------------------------------------------
# move_track
# ---------------------------------------------------------------------------


def test_move_track_moves_file_and_updates_path(tmp_path):
    src_dir = tmp_path / "source"
    src_dir.mkdir()
    lib = tmp_path / "library"

    track = Track(
        path=src_dir / "song.m4a",
        artist="Radiohead",
        album="OK Computer",
        year="1997",
        title="Paranoid Android",
        track_number=2,
    )
    track.path.touch()

    result = move_track(track, lib)

    expected = lib / "Radiohead" / "OK Computer (1997)" / "02 Paranoid Android.m4a"
    assert result == expected
    assert track.path == expected
    assert expected.exists()
    assert not (src_dir / "song.m4a").exists()


def test_move_track_creates_parent_directories(tmp_path):
    src = tmp_path / "song.m4a"
    src.touch()
    lib = tmp_path / "deep" / "library"

    track = Track(
        path=src,
        artist="Nirvana",
        album="Nevermind",
        year="1991",
        title="Smells Like Teen Spirit",
        track_number=1,
    )

    move_track(track, lib)

    assert track.path.exists()
    assert track.path.parent.is_dir()


def test_move_track_dry_run_does_not_move(tmp_path):
    src = tmp_path / "song.m4a"
    src.touch()
    lib = tmp_path / "library"

    track = Track(
        path=src,
        artist="Pink Floyd",
        album="The Wall",
        year="1979",
        title="Comfortably Numb",
        track_number=6,
    )

    result = move_track(track, lib, dry_run=True)

    # Source still exists
    assert src.exists()
    # Destination does NOT exist
    assert not result.exists()
    # track.path is updated to the destination even in dry_run
    assert track.path == result


# ---------------------------------------------------------------------------
# delete_original_wav
# ---------------------------------------------------------------------------


def test_delete_original_wav_removes_file(tmp_path):
    wav = tmp_path / "original.wav"
    wav.touch()

    delete_original_wav(wav)

    assert not wav.exists()


def test_delete_original_wav_dry_run_keeps_file(tmp_path):
    wav = tmp_path / "original.wav"
    wav.touch()

    delete_original_wav(wav, dry_run=True)

    assert wav.exists()
