# music-library-manager

CLI tool for organizing CD and LP rips into a tagged, structured music library — optimized for iPod Classic playback.

## What it does

Given a directory of WAV files (e.g. CD rips), it will:

1. Convert WAV → ALAC (`.m4a`) — lossless, iPod-compatible, with proper metadata support
2. Identify each track via acoustic fingerprinting (AcoustID + MusicBrainz)
3. Write full tags (artist, album, year, track number, genre) and embed cover art
4. Move files to `<input_dir>/artist/album (YEAR)/song_name.m4a`
5. Delete the original WAV

Stem separation is available as a separate command, outputting to `<input_dir>/stems/artist/album (YEAR)/song_name/`.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- ffmpeg (`brew install ffmpeg`)

## Installation

```bash
git clone git@github.com:caique-lima/music-library-manager.git
cd music-library-manager
uv sync
```

For stem generation, install the optional dependency:

```bash
uv sync --extra stems
```

## Usage

```bash
# Organize a directory of WAV files
uv run music-manager process /path/to/rips

# Preview without making changes
uv run music-manager process /path/to/rips --dry-run

# Generate stems for a track
uv run music-manager stems /path/to/track.m4a
```

## Output structure

```
input_dir/
  Pink Floyd/
    The Dark Side of the Moon (1973)/
      01 Speak to Me.m4a
      02 Breathe.m4a
  stems/
    Pink Floyd/
      The Dark Side of the Moon (1973)/
        02 Breathe/
          vocals.wav
          drums.wav
          bass.wav
          other.wav
```

## Development

```bash
uv sync --extra dev
uv run pytest
uv run pytest tests/test_convert.py::test_wav_to_alac  # single test
```
