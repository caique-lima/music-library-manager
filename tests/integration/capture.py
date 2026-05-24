#!/usr/bin/env python3
"""Capture a fingerprint fixture from a real audio file.

Extracts the chromaprint fingerprint and duration from a file and appends
an entry to tests/integration/fixtures/fingerprints.json. Run this once
when adding a new test case; the fixture is committed and tests use it
without needing the original audio.

Usage:
    uv run python tests/integration/capture.py /path/to/track.m4a \\
        --name "artist_title_slug" \\
        --title "Track Title" \\
        --artist "Artist Name" \\
        --album "Album Name" \\
        --year "YYYY"

Optional:
    --album-artist "Album Artist"   (only needed for feat. tracks)
    --description "Why this case"   (short note on what edge case it covers)
    --replace                       (overwrite an existing fixture with the same name)
"""

import argparse
import json
import re
import sys
from pathlib import Path

FIXTURES_PATH = Path(__file__).parent / "fixtures" / "fingerprints.json"


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture a fingerprint fixture from a real audio file."
    )
    parser.add_argument("path", help="Audio file to fingerprint")
    parser.add_argument("--name", help="Fixture name (snake_case); auto-derived if omitted")
    parser.add_argument("--title", required=True)
    parser.add_argument("--artist", required=True)
    parser.add_argument("--album", required=True)
    parser.add_argument("--year", required=True)
    parser.add_argument("--album-artist", default="")
    parser.add_argument("--description", default="")
    parser.add_argument("--replace", action="store_true", help="Overwrite existing fixture with same name")
    args = parser.parse_args()

    try:
        import acoustid
    except ImportError:
        print("Error: pyacoustid is not installed. Run: uv sync --extra dev", file=sys.stderr)
        sys.exit(1)

    path = Path(args.path)
    if not path.exists():
        print(f"Error: file not found: {path}", file=sys.stderr)
        sys.exit(1)

    name = args.name or f"{_slug(args.artist)}_{_slug(args.title)}"

    print(f"Fingerprinting {path.name}...")
    duration_s, fingerprint_bytes = acoustid.fingerprint_file(str(path))
    fingerprint = (
        fingerprint_bytes.decode("utf-8")
        if isinstance(fingerprint_bytes, bytes)
        else fingerprint_bytes
    )
    duration_ms = int(duration_s * 1000)
    print(f"  Duration: {duration_s:.1f}s  Fingerprint: {fingerprint[:24]}...")

    expected: dict = {
        "title": args.title,
        "artist": args.artist,
        "album": args.album,
        "year": args.year,
    }
    if args.album_artist:
        expected["album_artist"] = args.album_artist

    fixture: dict = {
        "name": name,
        "fingerprint": fingerprint,
        "duration_ms": duration_ms,
        "expected": expected,
    }
    if args.description:
        fixture["description"] = args.description
        # keep description after name for readability
        fixture = {"name": name, "description": args.description, **{k: v for k, v in fixture.items() if k not in ("name", "description")}}

    existing: list = json.loads(FIXTURES_PATH.read_text()) if FIXTURES_PATH.exists() else []
    names = [f["name"] for f in existing]

    if name in names:
        if not args.replace:
            print(f"Error: fixture '{name}' already exists. Use --replace to overwrite.", file=sys.stderr)
            sys.exit(1)
        existing = [f for f in existing if f["name"] != name]
        print(f"Replacing existing fixture '{name}'.")

    existing.append(fixture)
    FIXTURES_PATH.write_text(json.dumps(existing, indent=2, ensure_ascii=False) + "\n")
    print(f"Saved fixture '{name}' → {FIXTURES_PATH}")


if __name__ == "__main__":
    main()
