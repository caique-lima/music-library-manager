import asyncio
from pathlib import Path

import requests
from shazamio import Shazam

from music_manager.track import Track


def _parse(result: dict, path: Path) -> Track | None:
    track = result.get("track")
    if not track:
        return None

    title = track.get("title", "")
    artist = track.get("subtitle", "")
    genre = track.get("genres", {}).get("primary", "")

    album = ""
    year = ""
    for entry in track.get("sections", [{}])[0].get("metadata", []):
        if entry.get("title") == "Album":
            album = entry.get("text", "")
        elif entry.get("title") == "Released":
            year = entry.get("text", "")[:4]

    cover_art = b""
    cover_url = track.get("images", {}).get("coverart", "")
    if cover_url:
        try:
            resp = requests.get(cover_url, timeout=10)
            if resp.status_code == 200:
                cover_art = resp.content
        except Exception:
            pass

    return Track(
        path=path,
        title=title,
        artist=artist,
        album=album,
        year=year,
        genre=genre,
        cover_art=cover_art,
    )


async def _recognize(path: Path) -> dict:
    return await Shazam().recognize(str(path))


def identify_shazam(path: Path) -> Track | None:
    """Identify a track via Shazam. Returns None if no match found."""
    result = asyncio.run(_recognize(path))
    return _parse(result, path)
