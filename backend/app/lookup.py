"""Resolves a single-track link from a platform we can't download from
directly (Spotify, Apple Music, Deezer, Tidal — all DRM-protected) to a
matching YouTube/SoundCloud track, by reading the page's title and
searching for it."""
from __future__ import annotations

import re
import urllib.request

import yt_dlp

LOOKUP_DOMAINS = (
    "open.spotify.com",
    "music.apple.com",
    "deezer.com",
    "tidal.com",
    "listen.tidal.com",
)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Most music platforms fill <title>/og:title with something SEO-friendly
# like "Song Name - song by Artist | Spotify" or "Song by Artist on Apple
# Music" — good enough as a search query once we strip the site branding.
_META_PATTERNS = [
    re.compile(r'<meta property="og:title" content="([^"]+)"', re.IGNORECASE),
    re.compile(r'<meta name="twitter:title" content="([^"]+)"', re.IGNORECASE),
    re.compile(r"<title>([^<]+)</title>", re.IGNORECASE),
]

# Trailing site branding gets dropped outright.
_SUFFIXES_TO_STRIP = [
    r"\s*\|\s*Spotify\s*$",
    r"\s*on Apple Music\s*$",
    r"\s*-\s*Listen on Deezer\s*$",
    r"\s*\|\s*Deezer\s*$",
    r"\s*\|\s*TIDAL\s*$",
]

# Connecting words turn into a plain separator so both the song and the
# artist survive into the search query (e.g. "Song - song by Artist" ->
# "Song - Artist"), tried in order, first match wins.
_CONNECTORS = [
    r"\s*-\s*song and lyrics by\s*",
    r"\s*-\s*song by\s*",
    r"\s*-\s*Single by\s*",
    r"\s+by\s+",
]


def is_lookup_domain(url: str) -> bool:
    return any(domain in url for domain in LOOKUP_DOMAINS)


def _clean_title(raw: str) -> str:
    title = raw.replace("&amp;", "&").replace("&#39;", "'").replace("&quot;", '"')
    for suffix in _SUFFIXES_TO_STRIP:
        title = re.sub(suffix, "", title, flags=re.IGNORECASE)
    for connector in _CONNECTORS:
        new_title = re.sub(connector, " - ", title, count=1, flags=re.IGNORECASE)
        if new_title != title:
            title = new_title
            break
    return title.strip(" ‎‏-|")


def _fetch_query(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=15) as resp:
        html = resp.read(200_000).decode("utf-8", errors="ignore")

    for pattern in _META_PATTERNS:
        match = pattern.search(html)
        if match:
            title = _clean_title(match.group(1))
            if title:
                return title

    raise RuntimeError(
        "No se pudo leer el título de esta pista para buscarla en YouTube/SoundCloud."
    )


def resolve_foreign_track(url: str) -> dict:
    """Best-effort match: reads the track's title/artist off the page and
    searches YouTube first, then SoundCloud. Returns {"url", "title"} of
    the closest match found, or raises if nothing turned up anywhere."""
    query = _fetch_query(url)

    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "socket_timeout": 20,
        "retries": 3,
    }
    for search_prefix in ("ytsearch1", "scsearch1"):
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f"{search_prefix}:{query}", download=False)
            entries = info.get("entries") or []
            if entries and entries[0]:
                found = entries[0]
                found_url = found.get("url") or found.get("webpage_url")
                if found_url:
                    return {"url": found_url, "title": found.get("title") or query}
        except Exception:  # noqa: BLE001
            continue

    raise RuntimeError(f'No se encontró "{query}" en YouTube ni SoundCloud.')
