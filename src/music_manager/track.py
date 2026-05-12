from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Track:
    path: Path
    artist: str = ""
    album: str = ""
    year: str = ""
    title: str = ""
    track_number: int = 0
    genre: str = ""
    cover_art: bytes = field(default=b"", repr=False)
    musicbrainz_recording_id: str = ""
