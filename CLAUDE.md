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
uv run music-manager stems <file>                              # stem generation (stub)

# Run tests
uv run pytest
uv run pytest tests/test_organize.py::test_destination_path_fully_populated  # single test
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

All tracks run concurrently via `ThreadPoolExecutor` in `cli.py`. Results are printed as each completes via `as_completed`.

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
```

`album_artist` is the key to grouping feat. tracks correctly — `organize.py` uses it for the folder, falling back to `artist` when empty.

### Identification strategy (`identify.py` + `shazam.py`)

- `identify()` tries AcoustID first (if key provided), falls back to `identify_shazam()`
- AcoustID path: `pyacoustid` fingerprints the file → MusicBrainz API for metadata
- Shazam path: `shazamio` (async, called via `asyncio.run()` — safe across threads as each call creates its own event loop) → iTunes lookup API for track number and `collectionArtistName`

### HTTP caching (`cache.py`)

`fetch_url(url)` is an `lru_cache(maxsize=256)` wrapper around `requests.get`. Used by both `shazam.py` (cover art, iTunes lookup) and `tag.py` (MusicBrainz Cover Art Archive). Deduplicates fetches for the same URL across concurrent threads — critical for albums where all tracks share the same cover art URL.

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
| `demucs` | Stem separation (optional extra, not yet wired) |
| `click` | CLI |

## What's next

- Phase 5: Demucs stem generation command — output to `input_dir/stems/album_artist/album (YEAR)/title/{vocals,drums,bass,other}.wav`
- Phase 6: progress bars, config file (default workers, preferred model)
