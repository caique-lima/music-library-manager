# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

CLI tool for managing a personal music library sourced from CD rips (WAV files from a Fiio DM13) and LP rips. Targets an iPod 6th/7th generation as the primary playback device.

Core pipeline per track: convert WAV → ALAC → fingerprint → fetch metadata from MusicBrainz → tag → organize into folder structure → delete original WAV.

Stem generation is a separate on-demand command (uses Demucs, runs locally on Apple Silicon).

## Commands

Once the project is scaffolded (Phase 1):

```bash
# Install dependencies
uv sync --extra dev

# Run the tool
uv run music-manager process <input_dir>            # full pipeline: convert, tag, organize
uv run music-manager process <input_dir> --dry-run  # preview moves without writing

uv run music-manager stems <file_or_glob>           # generate stems for a specific track

# Run tests
uv run pytest

# Run a single test
uv run pytest tests/test_convert.py::test_wav_to_alac
```

## Architecture

### Pipeline (Phase 1–4)

```
input_dir/
  *.wav
    │
    ▼
  ffmpeg        → convert WAV → ALAC (.m4a)
    │
    ▼
  pyacoustid    → acoustic fingerprint
  MusicBrainz   → resolve artist / album / year / title / track#
    │
    ▼
  mutagen       → write MP4 tags + embed cover art (Cover Art Archive)
    │
    ▼
  organize      → move to input_dir/artist/album (YEAR)/song_name.m4a
                  delete original WAV
```

### Stem generation (Phase 5)

```
stems command
    │
    ▼
  Demucs        → separates vocals / drums / bass / other
    │
    ▼
  output        → input_dir/stems/artist/album (YEAR)/song_name/{vocals,drums,bass,other}.wav
```

Stems stay as WAV — they are for DAW use, not the iPod.

### Key dependencies

| Library | Role |
|---|---|
| `ffmpeg-python` | WAV → ALAC conversion |
| `pyacoustid` + `chromaprint` | Audio fingerprinting |
| `mutagen` | Reading/writing MP4 tags |
| `requests` | MusicBrainz & Cover Art Archive API |
| `demucs` | Stem separation (local, Apple Silicon) |
| `click` | CLI interface |

### File format decision

**WAV → ALAC (.m4a)** — lossless (no quality loss from CD rips), solid metadata support via the M4A container, natively supported by iPod Classic. AAC 256kbps is the fallback if iPod storage becomes a constraint.

### MusicBrainz integration

- Fingerprint with AcoustID first; fall back to manual prompt if no match
- Must include a User-Agent header per MusicBrainz API policy
- Configurable via a config file (MusicBrainz username, preferred stem model, etc.)

## Planned phases

1. Project skeleton + WAV → ALAC conversion
2. AcoustID fingerprinting + MusicBrainz lookup
3. Metadata tagging + cover art embedding
4. File organization + original WAV cleanup
5. Demucs stem generation command
6. Polish: progress bars, logging, dry-run, config file
