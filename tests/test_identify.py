"""Tests for music_manager.identify — no real network calls are made."""
import json
from pathlib import Path
from unittest.mock import call, patch

import pytest

from music_manager.track import Track
from music_manager.identify import (
    _best_release,
    _fetch_from_musicbrainz,
    _itunes_search_enrich,
    _join_artists,
    _normalize_feat,
    _score_release,
    fingerprint,
    identify,
    lookup_musicbrainz,
)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

FAKE_PATH = Path("/tmp/fake_song.m4a")
FAKE_API_KEY = "test-api-key"

# A realistic nested AcoustID result dict (as produced when
# meta="recordings releases releasegroups tracks" is requested).
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

# A MusicBrainz get_recording_by_id response (for tuple-form fallback).
MOCK_MB_RECORDING = {
    "recording": {
        "id": "mb-recording-uuid-1234",
        "title": "Still D.R.E.",
        "artist-credit": [
            {"artist": {"id": "dre-uuid", "name": "Dr. Dre"}, "joinphrase": " feat. "},
            {"artist": {"id": "snoop-uuid", "name": "Snoop Dogg"}, "joinphrase": ""},
        ],
        "release-list": [
            {
                "id": "release-uuid",
                "title": "2001",
                "date": "1999-11-16",
                # Release-level artist credit: album artist only, no feat.
                "artist-credit": [
                    {"artist": {"id": "dre-uuid", "name": "Dr. Dre"}, "joinphrase": ""},
                ],
                "medium-list": [
                    {
                        "track-list": [{"position": "1"}]
                    }
                ],
            }
        ],
    }
}


# ---------------------------------------------------------------------------
# _normalize_feat
# ---------------------------------------------------------------------------


def test_normalize_feat_featuring():
    assert _normalize_feat("Dr. Dre Featuring Eminem") == "Dr. Dre feat. Eminem"


def test_normalize_feat_featuring_case_insensitive():
    assert _normalize_feat("Drake FEATURING 21 Savage") == "Drake feat. 21 Savage"


def test_normalize_feat_ft_dot():
    assert _normalize_feat("Tyler Ft. Frank Ocean") == "Tyler feat. Frank Ocean"


def test_normalize_feat_ft_no_dot():
    assert _normalize_feat("Jay-Z Ft Kanye West") == "Jay-Z feat. Kanye West"


def test_normalize_feat_already_canonical():
    assert _normalize_feat("Dr. Dre feat. Eminem") == "Dr. Dre feat. Eminem"


def test_normalize_feat_no_change_for_solo():
    assert _normalize_feat("Radiohead") == "Radiohead"


# ---------------------------------------------------------------------------
# _join_artists
# ---------------------------------------------------------------------------


def test_join_artists_single():
    assert _join_artists([{"name": "Radiohead"}]) == "Radiohead"


def test_join_artists_multiple():
    result = _join_artists([{"name": "Dr. Dre"}, {"name": "Eminem"}])
    assert result == "Dr. Dre feat. Eminem"


def test_join_artists_three():
    result = _join_artists([{"name": "A"}, {"name": "B"}, {"name": "C"}])
    assert result == "A feat. B feat. C"


def test_join_artists_empty():
    assert _join_artists([]) == ""


def test_join_artists_skips_blank_names():
    assert _join_artists([{"name": ""}, {"name": "Radiohead"}]) == "Radiohead"


# ---------------------------------------------------------------------------
# _score_release / _best_release
# ---------------------------------------------------------------------------


def test_score_release_album_beats_single():
    album = {"date": "1997", "releasegroups": [{"type": "Album", "secondarytypes": []}]}
    single = {"date": "1997", "releasegroups": [{"type": "Single", "secondarytypes": []}]}
    assert _score_release(album) < _score_release(single)


def test_score_release_penalises_compilation():
    album = {"date": "1997", "releasegroups": [{"type": "Album", "secondarytypes": []}]}
    comp = {"date": "1997", "releasegroups": [{"type": "Album", "secondarytypes": ["Compilation"]}]}
    assert _score_release(album) < _score_release(comp)


def test_score_release_prefers_dated_over_undated():
    dated = {"date": "1997", "releasegroups": [{"type": "Album", "secondarytypes": []}]}
    undated = {"releasegroups": [{"type": "Album", "secondarytypes": []}]}
    assert _score_release(dated) < _score_release(undated)


def test_score_release_no_releasegroups_is_neutral():
    release = {"date": "1997"}
    score = _score_release(release)
    assert isinstance(score, tuple) and len(score) == 3


def test_best_release_picks_album_over_single():
    album = {"title": "The Album", "date": "2000", "releasegroups": [{"type": "Album", "secondarytypes": []}]}
    single = {"title": "The Single", "date": "2000", "releasegroups": [{"type": "Single", "secondarytypes": []}]}
    assert _best_release([single, album]) == album


def test_best_release_empty_returns_empty_dict():
    assert _best_release([]) == {}


# ---------------------------------------------------------------------------
# fingerprint()
# ---------------------------------------------------------------------------


def test_fingerprint_calls_acoustid_fingerprint_file():
    fake_fp = b"AQAAAE..."
    with patch("music_manager.identify.acoustid.fingerprint_file", return_value=(240, fake_fp)) as mock_fp:
        result = fingerprint(FAKE_PATH)
    mock_fp.assert_called_once_with(str(FAKE_PATH))
    assert result == fake_fp


# ---------------------------------------------------------------------------
# lookup_musicbrainz()
# ---------------------------------------------------------------------------


def test_lookup_musicbrainz_parses_response():
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
    assert track.cover_art == b""


def test_lookup_musicbrainz_joins_multiple_artists():
    result_dict = {
        "recordings": [
            {
                "id": "mb-id",
                "title": "Still D.R.E.",
                "artists": [{"name": "Dr. Dre"}, {"name": "Snoop Dogg"}],
                "releases": [],
            }
        ]
    }
    with (
        patch("music_manager.identify.acoustid.match", return_value=iter([result_dict])),
        patch("music_manager.identify.musicbrainzngs.set_useragent"),
    ):
        track = lookup_musicbrainz(FAKE_PATH, FAKE_API_KEY)

    assert track is not None
    assert track.artist == "Dr. Dre feat. Snoop Dogg"


def test_lookup_musicbrainz_uses_release_artist_not_feat():
    """Release-level artists field (no feat.) takes priority over recording artists."""
    result_dict = {
        "recordings": [
            {
                "id": "mb-id",
                "title": "Still D.R.E.",
                "artists": [{"name": "Dr. Dre"}, {"name": "Snoop Dogg"}],
                "releases": [
                    {
                        "title": "2001",
                        "date": "1999",
                        "artists": [{"name": "Dr. Dre"}],
                        "releasegroups": [{"type": "Album", "secondarytypes": []}],
                        "mediums": [],
                    }
                ],
            }
        ]
    }
    with (
        patch("music_manager.identify.acoustid.match", return_value=iter([result_dict])),
        patch("music_manager.identify.musicbrainzngs.set_useragent"),
    ):
        track = lookup_musicbrainz(FAKE_PATH, FAKE_API_KEY)

    assert track is not None
    assert track.artist == "Dr. Dre"
    assert track.album_artist == ""


def test_lookup_musicbrainz_album_artist_empty_for_solo():
    with (
        patch("music_manager.identify.acoustid.match", return_value=iter([MOCK_RESULT_DICT])),
        patch("music_manager.identify.musicbrainzngs.set_useragent"),
    ):
        track = lookup_musicbrainz(FAKE_PATH, FAKE_API_KEY)

    assert track is not None
    assert track.album_artist == ""


def test_lookup_musicbrainz_picks_best_release():
    result_dict = {
        "recordings": [
            {
                "id": "mb-id",
                "title": "The Song",
                "artists": [{"name": "Radiohead"}],
                "releases": [
                    {
                        "title": "Compilation",
                        "date": "2005",
                        "releasegroups": [{"type": "Album", "secondarytypes": ["Compilation"]}],
                        "mediums": [],
                    },
                    {
                        "title": "OK Computer",
                        "date": "1997",
                        "releasegroups": [{"type": "Album", "secondarytypes": []}],
                        "mediums": [{"tracks": [{"position": 3}]}],
                    },
                ],
            }
        ]
    }
    with (
        patch("music_manager.identify.acoustid.match", return_value=iter([result_dict])),
        patch("music_manager.identify.musicbrainzngs.set_useragent"),
    ):
        track = lookup_musicbrainz(FAKE_PATH, FAKE_API_KEY)

    assert track is not None
    assert track.album == "OK Computer"
    assert track.track_number == 3


def test_lookup_musicbrainz_normalises_feat_in_artist():
    result_dict = {
        "recordings": [
            {
                "id": "mb-id",
                "title": "Song",
                "artists": [{"name": "A Featuring B"}],
                "releases": [],
            }
        ]
    }
    with (
        patch("music_manager.identify.acoustid.match", return_value=iter([result_dict])),
        patch("music_manager.identify.musicbrainzngs.set_useragent"),
    ):
        track = lookup_musicbrainz(FAKE_PATH, FAKE_API_KEY)

    assert track is not None
    assert "feat." in track.artist


def test_lookup_musicbrainz_returns_none_when_no_results():
    with (
        patch("music_manager.identify.acoustid.match", return_value=iter([])),
        patch("music_manager.identify.musicbrainzngs.set_useragent"),
    ):
        result = lookup_musicbrainz(FAKE_PATH, FAKE_API_KEY)
    assert result is None


def test_lookup_musicbrainz_returns_none_when_recordings_empty():
    empty_recordings_result = {"id": "x", "score": 0.5, "recordings": []}
    with (
        patch("music_manager.identify.acoustid.match", return_value=iter([empty_recordings_result])),
        patch("music_manager.identify.musicbrainzngs.set_useragent"),
    ):
        result = lookup_musicbrainz(FAKE_PATH, FAKE_API_KEY)
    assert result is None


def test_lookup_musicbrainz_sets_useragent():
    with (
        patch("music_manager.identify.acoustid.match", return_value=iter([MOCK_RESULT_DICT])),
        patch("music_manager.identify.musicbrainzngs.set_useragent") as mock_ua,
    ):
        lookup_musicbrainz(FAKE_PATH, FAKE_API_KEY)
    mock_ua.assert_called_once_with(
        "music-library-manager", "0.1", "https://github.com/caique-lima/music-library-manager"
    )


def test_lookup_musicbrainz_tuple_form_fetches_mb_data():
    """Tuple-form response should trigger a MusicBrainz data fetch."""
    tuple_result = (0.9, "mb-recording-uuid-1234", "Still D.R.E.", "Dr. Dre")
    mb_data = (
        {"id": "mb-recording-uuid-1234", "title": "Still D.R.E.", "artist-credit": [{"artist": {"name": "Dr. Dre"}, "joinphrase": ""}]},
        {"title": "2001", "date": "1999", "artist-credit": [{"artist": {"name": "Dr. Dre"}, "joinphrase": ""}], "medium-list": []},
    )
    with (
        patch("music_manager.identify.acoustid.match", return_value=iter([tuple_result])),
        patch("music_manager.identify.musicbrainzngs.set_useragent"),
        patch("music_manager.identify._fetch_mb_data", return_value=mb_data) as mock_fetch,
        patch("music_manager.identify._duration_diff_s", return_value=0),
    ):
        track = lookup_musicbrainz(FAKE_PATH, FAKE_API_KEY)

    mock_fetch.assert_called_once_with("mb-recording-uuid-1234")
    assert track is not None
    assert track.title == "Still D.R.E."
    assert track.artist == "Dr. Dre"


def test_lookup_musicbrainz_tuple_form_picks_best_candidate():
    """When multiple tuple results exist, the one with the better release wins."""
    results = [
        (0.99, "bad-id",  "Song", "Artist"),
        (0.99, "good-id", "Song", "Artist"),
    ]
    bad_data = (
        {"id": "bad-id", "title": "Song", "artist-credit": [{"artist": {"name": "Artist"}, "joinphrase": ""}], "release-list": []},
        {"title": "Compilation DVD", "date": "2005", "artist-credit": [], "medium-list": [{"format": "DVD-Video"}]},
    )
    good_data = (
        {"id": "good-id", "title": "Song", "artist-credit": [{"artist": {"name": "Artist"}, "joinphrase": ""}], "release-list": []},
        {"title": "Original Album", "date": "1997", "artist-credit": [], "medium-list": [{"format": "CD"}]},
    )
    with (
        patch("music_manager.identify.acoustid.match", return_value=iter(results)),
        patch("music_manager.identify.musicbrainzngs.set_useragent"),
        patch("music_manager.identify._fetch_mb_data", side_effect=[bad_data, good_data]),
        patch("music_manager.identify._duration_diff_s", return_value=0),
    ):
        track = lookup_musicbrainz(FAKE_PATH, FAKE_API_KEY)

    assert track is not None
    assert track.album == "Original Album"
    assert track.year == "1997"


def test_lookup_musicbrainz_tuple_form_uses_duration_as_tiebreaker():
    """When release quality ties, the candidate whose MB duration matches the file wins."""
    results = [
        (0.99, "wrong-id", "Wrong Song", "Artist"),  # first, many releases, wrong duration
        (0.99, "right-id", "Right Song", "Artist"),  # second, fewer releases, correct duration
    ]
    wrong_data = (
        {"id": "wrong-id", "title": "Wrong Song", "length": "232000",
         "artist-credit": [{"artist": {"name": "Artist"}, "joinphrase": ""}],
         "release-list": [{"id": f"r{i}"} for i in range(25)]},
        {"title": "Wrong Album", "date": "1992", "artist-credit": [], "medium-list": [{"format": "CD"}]},
    )
    right_data = (
        {"id": "right-id", "title": "Right Song", "length": "51000",
         "artist-credit": [{"artist": {"name": "Artist"}, "joinphrase": ""}],
         "release-list": [{"id": "r1"}, {"id": "r2"}]},
        {"title": "Right Album", "date": "1999", "artist-credit": [], "medium-list": [{"format": "CD"}]},
    )
    # File duration is 50.7s — matches "right-id" (51s), not "wrong-id" (232s)
    def fake_duration_diff(path, recording):
        return abs(50700 - int(recording.get("length", 0))) // 1000

    with (
        patch("music_manager.identify.acoustid.match", return_value=iter(results)),
        patch("music_manager.identify.musicbrainzngs.set_useragent"),
        patch("music_manager.identify._fetch_mb_data", side_effect=[wrong_data, right_data]),
        patch("music_manager.identify._duration_diff_s", side_effect=fake_duration_diff),
    ):
        track = lookup_musicbrainz(FAKE_PATH, FAKE_API_KEY)

    assert track is not None
    assert track.title == "Right Song"
    assert track.album == "Right Album"


def test_lookup_musicbrainz_tuple_form_uses_release_count_as_tiebreaker():
    """When format/VA/duration scores all tie, the candidate with more releases wins."""
    results = [
        (0.99, "older-id", "Older Song", "Artist"),
        (0.99, "newer-id", "Newer Song", "Artist"),
    ]
    older_data = (
        {"id": "older-id", "title": "Older Song", "artist-credit": [{"artist": {"name": "Artist"}, "joinphrase": ""}],
         "release-list": [{"id": "r1"}, {"id": "r2"}]},
        {"title": "Older Album", "date": "1992", "artist-credit": [], "medium-list": [{"format": "CD"}]},
    )
    newer_data = (
        {"id": "newer-id", "title": "Newer Song", "artist-credit": [{"artist": {"name": "Artist"}, "joinphrase": ""}],
         "release-list": [{"id": f"r{i}"} for i in range(25)]},
        {"title": "Newer Album", "date": "1998", "artist-credit": [], "medium-list": [{"format": "CD"}]},
    )
    with (
        patch("music_manager.identify.acoustid.match", return_value=iter(results)),
        patch("music_manager.identify.musicbrainzngs.set_useragent"),
        patch("music_manager.identify._fetch_mb_data", side_effect=[older_data, newer_data]),
        patch("music_manager.identify._duration_diff_s", return_value=30),  # both unknown
    ):
        track = lookup_musicbrainz(FAKE_PATH, FAKE_API_KEY)

    assert track is not None
    assert track.title == "Newer Song"
    assert track.album == "Newer Album"


# ---------------------------------------------------------------------------
# _fetch_from_musicbrainz()
# ---------------------------------------------------------------------------


def test_fetch_from_musicbrainz_uses_release_artist():
    """Release-level artist-credit (album artist, no feat.) is preferred."""
    with patch("music_manager.identify.musicbrainzngs.get_recording_by_id", return_value=MOCK_MB_RECORDING):
        track = _fetch_from_musicbrainz("mb-recording-uuid-1234", FAKE_PATH)

    assert track is not None
    assert track.artist == "Dr. Dre"
    assert track.album_artist == ""
    assert track.album == "2001"
    assert track.year == "1999"
    assert track.track_number == 1
    assert track.musicbrainz_recording_id == "mb-recording-uuid-1234"


def test_fetch_from_musicbrainz_falls_back_to_recording_artist_when_no_release_credit():
    """When no release-level artist-credit exists, fall back to recording's artist-credit."""
    mb_result = {
        "recording": {
            "id": "id",
            "title": "Song",
            "artist-credit": [
                {"artist": {"name": "Dr. Dre"}, "joinphrase": " feat. "},
                {"artist": {"name": "Eminem"}, "joinphrase": ""},
            ],
            "release-list": [
                {"id": "r1", "title": "Album", "date": "2001", "medium-list": []},
            ],
        }
    }
    with patch("music_manager.identify.musicbrainzngs.get_recording_by_id", return_value=mb_result):
        track = _fetch_from_musicbrainz("id", FAKE_PATH)

    assert track is not None
    assert track.artist == "Dr. Dre feat. Eminem"


def test_fetch_from_musicbrainz_falls_back_to_recording_artist_for_various_artists():
    """When release artist is Various Artists, use recording-level artist-credit instead."""
    mb_result = {
        "recording": {
            "id": "id",
            "title": "Angel",
            "artist-credit": [{"artist": {"name": "Massive Attack"}, "joinphrase": ""}],
            "release-list": [
                {
                    "id": "r1",
                    "title": "π: Music for the Motion Picture",
                    "date": "1998-07-21",
                    "artist-credit": [{"artist": {"name": "Various Artists"}, "joinphrase": ""}],
                    "medium-list": [],
                }
            ],
        }
    }
    with patch("music_manager.identify.musicbrainzngs.get_recording_by_id", return_value=mb_result):
        track = _fetch_from_musicbrainz("id", FAKE_PATH)

    assert track is not None
    assert track.artist == "Massive Attack"


def test_fetch_from_musicbrainz_returns_none_on_error():
    import musicbrainzngs as mb
    with patch(
        "music_manager.identify.musicbrainzngs.get_recording_by_id",
        side_effect=mb.WebServiceError("timeout"),
    ):
        result = _fetch_from_musicbrainz("some-id", FAKE_PATH)
    assert result is None


def test_fetch_from_musicbrainz_prefers_dated_release():
    mb_result = {
        "recording": {
            "id": "id",
            "title": "Song",
            "artist-credit": [{"artist": {"name": "Artist"}, "joinphrase": ""}],
            "release-list": [
                {"id": "r1", "title": "No Date Release", "medium-list": []},
                {"id": "r2", "title": "Dated Release", "date": "2001-01-01", "medium-list": []},
            ],
        }
    }
    with patch("music_manager.identify.musicbrainzngs.get_recording_by_id", return_value=mb_result):
        track = _fetch_from_musicbrainz("id", FAKE_PATH)

    assert track is not None
    assert track.album == "Dated Release"
    assert track.year == "2001"


# ---------------------------------------------------------------------------
# _itunes_search_enrich()
# ---------------------------------------------------------------------------

_ITUNES_RESULTS = json.dumps({
    "results": [
        {
            "trackName": "Paranoid Android",
            "primaryGenreName": "Alternative",
            "collectionName": "OK Computer",
            "collectionArtistName": "Radiohead",
            "releaseDate": "1997-05-21T07:00:00Z",
        }
    ]
}).encode()


def test_itunes_search_enrich_fills_genre():
    track = Track(path=FAKE_PATH, title="Paranoid Android", artist="Radiohead", album="OK Computer", album_artist="Radiohead")
    with patch("music_manager.identify.fetch_url", return_value=_ITUNES_RESULTS):
        _itunes_search_enrich(track)
    assert track.genre == "Alternative"


def test_itunes_search_enrich_fills_album():
    track = Track(path=FAKE_PATH, title="Paranoid Android", artist="Radiohead", album_artist="Radiohead")
    with patch("music_manager.identify.fetch_url", return_value=_ITUNES_RESULTS):
        _itunes_search_enrich(track)
    assert track.album == "OK Computer"


def test_itunes_search_enrich_fills_album_artist():
    track = Track(path=FAKE_PATH, title="Paranoid Android", artist="Radiohead", album="OK Computer")
    with patch("music_manager.identify.fetch_url", return_value=_ITUNES_RESULTS):
        _itunes_search_enrich(track)
    assert track.album_artist == "Radiohead"


def test_itunes_search_enrich_fills_year():
    track = Track(path=FAKE_PATH, title="Paranoid Android", artist="Radiohead", album="OK Computer")
    with patch("music_manager.identify.fetch_url", return_value=_ITUNES_RESULTS):
        _itunes_search_enrich(track)
    assert track.year == "1997"


def test_itunes_search_enrich_noop_when_all_populated():
    track = Track(
        path=FAKE_PATH, title="Song", artist="Artist",
        genre="Rock", album="The Album", album_artist="Artist",
        cover_art=b"\xff\xd8\xff",
    )
    with patch("music_manager.identify.fetch_url") as mock_fetch:
        _itunes_search_enrich(track)
    mock_fetch.assert_not_called()


def test_itunes_search_enrich_noop_without_title():
    track = Track(path=FAKE_PATH, artist="Radiohead")
    with patch("music_manager.identify.fetch_url") as mock_fetch:
        _itunes_search_enrich(track)
    mock_fetch.assert_not_called()


def test_itunes_search_enrich_handles_empty_response():
    track = Track(path=FAKE_PATH, title="Song", artist="Artist")
    with patch("music_manager.identify.fetch_url", return_value=b""):
        _itunes_search_enrich(track)
    assert track.genre == ""


def test_itunes_search_enrich_prefers_exact_title_match():
    results = json.dumps({
        "results": [
            {"trackName": "Wrong Song", "primaryGenreName": "Pop", "collectionName": "Wrong Album"},
            {"trackName": "My Song", "primaryGenreName": "Rock", "collectionName": "Right Album"},
        ]
    }).encode()
    track = Track(path=FAKE_PATH, title="My Song", artist="Artist")
    with patch("music_manager.identify.fetch_url", return_value=results):
        _itunes_search_enrich(track)
    assert track.album == "Right Album"
    assert track.genre == "Rock"


# ---------------------------------------------------------------------------
# identify()
# ---------------------------------------------------------------------------


def test_identify_returns_track_on_match():
    expected = Track(
        path=FAKE_PATH,
        title="Paranoid Android",
        artist="Radiohead",
        album="OK Computer",
        year="1997",
        track_number=2,
        musicbrainz_recording_id="mb-recording-uuid-1234",
    )
    with (
        patch("music_manager.identify.lookup_musicbrainz", return_value=expected),
        patch("music_manager.identify._itunes_search_enrich"),
    ):
        result = identify(FAKE_PATH, FAKE_API_KEY)
    assert result == expected


def test_identify_calls_itunes_enrich_after_acoustid():
    track = Track(path=FAKE_PATH, title="Song", artist="Artist")
    with (
        patch("music_manager.identify.lookup_musicbrainz", return_value=track),
        patch("music_manager.identify._itunes_search_enrich") as mock_enrich,
    ):
        identify(FAKE_PATH, FAKE_API_KEY)
    mock_enrich.assert_called_once_with(track)


def test_identify_returns_empty_track_when_no_match():
    with (
        patch("music_manager.identify.lookup_musicbrainz", return_value=None),
        patch("music_manager.identify._itunes_search_enrich"),
    ):
        result = identify(FAKE_PATH, FAKE_API_KEY)

    assert result.path == FAKE_PATH
    assert result.title == ""
    assert result.artist == ""
    assert result.album == ""
    assert result.year == ""
    assert result.track_number == 0
    assert result.musicbrainz_recording_id == ""
    assert result.cover_art == b""


def test_identify_returns_empty_track_when_no_api_key():
    result = identify(FAKE_PATH)
    assert result.path == FAKE_PATH
    assert result.title == ""
