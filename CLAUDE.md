# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

CLI tool for managing a personal music library sourced from CD rips (WAV files from a Fiio DM13) and LP rips. Targets an iPod 6th/7th generation as the primary playback device.

Core pipeline per track: convert WAV → ALAC → fingerprint → fetch metadata from MusicBrainz → tag → organize into folder structure → delete original WAV.

Stem generation is a separate on-demand command (uses Demucs, runs locally on Apple Silicon).

## Commands

```bash
# Install dependencies
uv sync --extra dev          # includes pytest
uv sync --extra stems        # adds demucs (large, optional)

# Run the tool
uv run music-manager process <input_dir>            # full pipeline: convert, tag, organize
uv run music-manager process <input_dir> --dry-run  # preview moves without writing
uv run music-manager stems <file_or_glob>           # generate stems for a specific track

# Run tests
uv run pytest
uv run pytest tests/test_convert.py::test_wav_to_alac_calls_ffmpeg  # single test
```

## Architecture

### Pipeline flow

```
input_dir/*.wav
    │
    ▼ convert.py
  ffmpeg → WAV → ALAC (.m4a), same directory
    │
    ▼ identify.py
  pyacoustid fingerprint → acoustid.match() → MusicBrainz API
  returns Track dataclass (artist, album, year, title, track_number, mb_id)
    │
    ▼ tag.py
  Cover Art Archive fetch → mutagen MP4 tag write
    │
    ▼ organize.py
  move to library_root/artist/album (YEAR)/NN title.m4a
  delete original WAV
```

Stem generation (Phase 5 — not yet implemented) will output to `input_dir/stems/artist/album (YEAR)/song_name/{vocals,drums,bass,other}.wav` as WAV for DAW use.

### Track dataclass (`track.py`)

The shared data model passed between all pipeline stages:

```python
@dataclass
class Track:
    path: Path
    artist: str
    album: str
    year: str           # 4-char string, e.g. "1997"
    title: str
    track_number: int   # 0 means unknown; omits numeric prefix in filename
    genre: str
    cover_art: bytes    # populated by tag.py, empty until then
    musicbrainz_recording_id: str
```

### Key behaviours to know

- `identify.py` handles two response shapes from `acoustid.match()`: raw dicts (when `meta="recordings releasegroups"`) and the simpler tuple form. Both are parsed.
- `organize.py` sanitizes path components (strips whitespace, replaces `/` with `-`). Falls back to `"Unknown Artist"` / `"Unknown Album"` for empty fields.
- `tag.py` skips writing any tag whose field is empty/zero — never writes blank strings to the file.
- `tag.py` fetches cover art from `coverartarchive.org/recording/{id}/front`; failure is silently ignored (best-effort).
- MusicBrainz User-Agent is set inside `identify.py` before every call, as required by their API policy.
- `cli.py` currently only wires up Phase 1 (conversion). Phases 2–4 modules are implemented but not yet connected in the `process` command.

### Key dependencies

| Library | Role |
|---|---|
| `ffmpeg-python` | WAV → ALAC conversion |
| `pyacoustid` + `musicbrainzngs` | Audio fingerprinting + MusicBrainz API |
| `mutagen` | Reading/writing MP4 tags |
| `requests` | Cover Art Archive HTTP fetch |
| `demucs` | Stem separation (optional extra) |
| `click` | CLI interface |

### File format

**WAV → ALAC (.m4a)** — lossless (no quality loss from CD rips), solid metadata support via the M4A container, natively supported by iPod Classic. AAC 256kbps is the documented fallback if storage becomes a constraint.

## What's next

- Wire `identify` → `tag` → `organize` into the `process` command in `cli.py` (needs AcoustID API key handling)
- Phase 5: Demucs stem generation command
- Phase 6: progress bars, logging, config file
