# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

CLI tool for managing a personal music library sourced from CD rips (WAV files from a Fiio DM13) and LP rips. Targets an iPod 6th/7th generation as the primary playback device.

Core pipeline per track: convert WAV → ALAC → identify → tag → organize into folder structure → delete original WAV.

Stem generation is a separate on-demand command (Phase 5 — not yet implemented).

## Commands

```bash
# Install dependencies
uv sync --extra dev          # includes pytest
uv sync --extra stems        # adds demucs (large, optional)

# Run the tool
uv run music-manager process <input_dir>                        # full pipeline
uv run music-manager process <input_dir> --dry-run             # preview only
uv run music-manager process <input_dir> --workers 8           # more concurrency
uv run music-manager process <input_dir> --api-key <key>       # prefer AcoustID over Shazam

uv run music-manager fix <input_dir>                           # re-identify/re-tag existing .m4a files (recursive, skips stems/)
uv run music-manager fix <input_dir> --api-key <key>

uv run music-manager benchmark <library_dir>                   # accuracy vs embedded tags in organized library
uv run music-manager benchmark <library_dir> --no-shazam --output eval/report.json
uv run music-manager benchmark <library_dir> --sample 3        # 3 random tracks per album

uv run music-manager evaluate <input_dir>                      # identify WAV files without converting
uv run music-manager evaluate <input_dir> --records eval/records.yaml --output eval/report.json
uv run music-manager evaluate <input_dir> --no-shazam --sample 2

uv run music-manager stems <file>                              # stem generation (stub)

# Run tests
uv run pytest
uv run pytest tests/test_organize.py::test_destination_path_fully_populated  # single test

# Run live AcoustID integration tests (requires API key, hits real APIs)
ACOUSTID_API_KEY=<key> uv run pytest tests/integration/ -m integration -v -s
ACOUSTID_ACCURACY_THRESHOLD=0.90 ACOUSTID_API_KEY=<key> uv run pytest tests/integration/ -m integration -v -s

# Add a new integration test fixture from a real audio file
uv run python tests/integration/capture.py /path/to/track.m4a \
    --title "Track Title" --artist "Artist" --album "Album" --year "YYYY"

# Render an eval report
uv run python eval/report.py eval/report.json
```

`ACOUSTID_API_KEY` env var is the alternative to `--api-key`.

## Architecture

### Per-track pipeline

```
input_dir/*.wav
    │
    ▼ convert.py       wav_to_alac()
  ffmpeg → ALAC (.m4a), same directory
    │
    ▼ identify.py      identify()
  AcoustID (if key) → MusicBrainz   ← preferred, richer metadata
  Shazam fallback   → iTunes API    ← used when AcoustID unavailable
  returns populated Track dataclass
    │
    ▼ tag.py           tag_track()
  fetch cover art (cached) → mutagen MP4 tag write
    │
    ▼ organize.py      move_track() + delete_original_wav()
  library_root / album_artist / album (YEAR) / NN title.m4a
  delete original WAV
```

All tracks run concurrently via `ThreadPoolExecutor` in `cli.py`. A Rich live display shows per-worker phase and a rolling result log. Error tracks are moved to `input_dir/failed_conversion/` rather than left in place. Duplicate WAVs (MD5-matched) are deleted before processing begins.

### Track dataclass (`track.py`)

Shared data model passed between all pipeline stages:

```python
@dataclass
class Track:
    path: Path
    artist: str          # full track artist (e.g. "Dr. Dre, Charis Henry & Mel-Man")
    album_artist: str    # album-level artist used for folder (e.g. "Dr. Dre") — from iTunes collectionArtistName
    album: str
    year: str            # 4-char string
    title: str
    track_number: int    # 0 = unknown; omits numeric prefix in filename
    genre: str
    cover_art: bytes     # populated during identification, empty until then
    musicbrainz_recording_id: str
    musicbrainz_release_id: str
    acoustid_score: float   # 0.0 = not set; used by benchmark/score to flag weak matches
```

All fields except `path` have empty/zero defaults. `album_artist` is used for folder grouping, falling back to `artist` when empty.

### Identification strategy (`identify.py` + `shazam.py`)

- `identify()` tries AcoustID first (if key provided), falls back to `identify_shazam()`
- AcoustID path: `pyacoustid` fingerprints the file → MusicBrainz API for metadata
- Shazam path: `shazamio` (async, called via `asyncio.run()` — safe across threads as each call creates its own event loop) → iTunes lookup API for track number and `collectionArtistName`

### HTTP caching (`cache.py`)

`fetch_url(url)` is an `lru_cache(maxsize=256)` wrapper around `requests.get`. Used by both `shazam.py` (cover art, iTunes lookup) and `tag.py` (MusicBrainz Cover Art Archive). Deduplicates fetches for the same URL across concurrent threads — critical for albums where all tracks share the same cover art URL.

### Evaluation & benchmarking

Two distinct workflows for measuring identification accuracy:

**`evaluate` command** (`evaluate.py` + `score.py`) — runs against raw WAV files, no conversion performed:
- `evaluate_track()` fingerprints the WAV directly via `identify()` and optionally runs Shazam
- `score_report()` aggregates `EvalResult` lists into a JSON report with per-record breakdowns, field coverage, AcoustID score distribution, Shazam cross-agreement, iPod-weighted quality scores, and recommendations
- `eval/records.yaml` provides optional `known_albums` ground truth for album accuracy measurement
- WAV naming convention `TRK<X>~<N>.WAV` groups tracks by record index (`parse_record_index()`)

**Integration tests** (`tests/integration/`) — live AcoustID + MusicBrainz accuracy tests, no audio files committed:
- Fixtures in `tests/integration/fixtures/fingerprints.json` store real chromaprint fingerprint strings (captured via `capture.py`) with ground-truth expected metadata
- `test_acoustid.py` injects stored fingerprints via `acoustid.fingerprint_file` mock, suppresses Shazam, and hits the real AcoustID + MusicBrainz APIs
- Reports a field-level accuracy score (title/artist/album/year) across all fixtures; the test passes when `passed_checks / total_checks >= threshold`
- Threshold is configured in `pyproject.toml` under `[tool.music-manager] integration_accuracy_threshold` and overridable via `ACOUSTID_ACCURACY_THRESHOLD` env var — raise it as pipeline accuracy improves, never lower it to make tests pass
- `_duration_diff_s` is also mocked using each fixture's `duration_ms` so the MusicBrainz recording tiebreaker works without a real file on disk
- `capture.py` is a CLI helper: fingerprints a real audio file and appends an entry to the fixtures JSON

**`benchmark` command** (`benchmark.py`) — runs against an already-organized m4a library (e.g. `~/personal_rips`):
- Uses embedded m4a tags as ground truth (`read_ground_truth()`)
- `_field_match()` uses fuzzy similarity with edition/feat. normalization to handle variant album names
- Reports perfect-match %, per-field match %, per-album breakdown, and sorted failure list

### Key behaviours

- WAV glob is case-insensitive (handles `.WAV` from Fiio DM13 alongside `.wav`)
- `organize.py` sanitizes path components: strips whitespace, replaces `/` with `-`
- `tag.py` skips writing any tag whose field is empty/zero
- Cover art from Shazam is fetched and embedded during identification, so `tag_track()` skips the MusicBrainz Cover Art Archive fetch when `cover_art` is already populated
- `chromaprint` (`fpcalc` binary) must be installed separately: `brew install chromaprint`

### Key dependencies

| Library | Role |
|---|---|
| `ffmpeg-python` | WAV → ALAC conversion |
| `pyacoustid` + `musicbrainzngs` | Fingerprinting + MusicBrainz API |
| `shazamio` | Shazam recognition (async) |
| `mutagen` | MP4 tag reading/writing |
| `requests` | HTTP (cover art, iTunes, MusicBrainz) |
| `rich` | Live CLI progress display |
| `demucs` | Stem separation (optional extra, not yet wired) |
| `click` | CLI |

## What's next

- Phase 5: Demucs stem generation command — output to `input_dir/stems/album_artist/album (YEAR)/title/{vocals,drums,bass,other}.wav`
- Phase 6: progress bars, config file (default workers, preferred model)
