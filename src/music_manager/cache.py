import functools
import requests


@functools.lru_cache(maxsize=256)
def fetch_url(url: str) -> bytes:
    """Fetch a URL and return its content, caching by URL across threads.

    Returns b"" on any failure. lru_cache is thread-safe in CPython.
    """
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            return resp.content
    except Exception:
        pass
    return b""
