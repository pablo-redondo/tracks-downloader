"""Resolves a single-track link from a platform we can't download from
directly (Spotify, Apple Music, Deezer, Tidal — all DRM-protected) to a
matching YouTube/SoundCloud track.

Prefers each platform's public JSON API (oEmbed / iTunes lookup / Deezer
API) over scraping the page's HTML: those pages can serve a cookie-consent
or bot-check interstitial instead of the real track page depending on
region/headers, and scraping that silently would poison the search with
unrelated text (e.g. ending up searching "Spotify Web Player" instead of
the actual song). The JSON APIs are meant for exactly this kind of
third-party lookup and don't have that problem.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from typing import Optional

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


def _http_get(url: str, accept: str = "*/*", max_bytes: int = 200_000) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT, "Accept": accept})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read(max_bytes)


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


def _scrape_title(url: str) -> Optional[str]:
    """Best-effort HTML scrape. May return None or garbage (e.g. a cookie
    wall's title) — callers that use this as the *only* source should treat
    it as unreliable; callers with a trusted API result should only accept
    this if it corroborates that result (see _spotify_query)."""
    html = _http_get(url, accept="text/html").decode("utf-8", errors="ignore")
    for pattern in _META_PATTERNS:
        match = pattern.search(html)
        if match:
            title = _clean_title(match.group(1))
            if title:
                return title
    return None


def _spotify_query(url: str) -> str:
    # oEmbed is Spotify's own public API for third-party link previews
    # (used by Slack/Discord/etc.) — unlike the plain page, it won't serve
    # a cookie-consent/region interstitial, so it's the reliable source
    # for the track title. It doesn't include the artist, though.
    oembed_url = "https://open.spotify.com/oembed?url=" + urllib.parse.quote(url, safe="")
    data = json.loads(_http_get(oembed_url, accept="application/json").decode("utf-8", errors="ignore"))
    track_title = (data.get("title") or "").strip()
    if not track_title:
        raise RuntimeError("No se pudo leer el título de esta pista de Spotify.")

    try:
        html_title = _scrape_title(url)
    except Exception:  # noqa: BLE001
        html_title = None
    # Only trust the richer (title + artist) HTML scrape if it actually
    # mentions the track oEmbed gave us — otherwise it's probably a
    # cookie-wall/bot-check page and we fall back to the title alone.
    if html_title and track_title.lower() in html_title.lower():
        return html_title
    return track_title


def _apple_music_query(url: str) -> str:
    # iTunes' public lookup API (no auth) covers Apple Music catalog IDs.
    match = re.search(r"[?&]i=(\d+)", url) or re.search(r"/song/[^/]+/(\d+)", url)
    if not match:
        raise RuntimeError("No se pudo identificar la pista en ese enlace de Apple Music.")
    data = json.loads(
        _http_get(f"https://itunes.apple.com/lookup?id={match.group(1)}", accept="application/json").decode(
            "utf-8", errors="ignore"
        )
    )
    results = data.get("results") or []
    if not results:
        raise RuntimeError("No se encontraron datos de esa pista en Apple Music.")
    title = results[0].get("trackName")
    artist = results[0].get("artistName")
    if not title:
        raise RuntimeError("No se pudo leer el título de esta pista de Apple Music.")
    return f"{title} - {artist}" if artist else title


def _deezer_query(url: str) -> str:
    # Deezer's public API (no auth) — track share links carry the numeric id.
    match = re.search(r"/track/(\d+)", url)
    if not match:
        raise RuntimeError("No se pudo identificar la pista en ese enlace de Deezer.")
    data = json.loads(
        _http_get(f"https://api.deezer.com/track/{match.group(1)}", accept="application/json").decode(
            "utf-8", errors="ignore"
        )
    )
    title = data.get("title")
    artist = (data.get("artist") or {}).get("name")
    if not title:
        raise RuntimeError("No se pudo leer el título de esta pista de Deezer.")
    return f"{title} - {artist}" if artist else title


def _fetch_query(url: str) -> str:
    if "open.spotify.com" in url:
        return _spotify_query(url)
    if "music.apple.com" in url:
        return _apple_music_query(url)
    if "deezer.com" in url:
        return _deezer_query(url)
    # Tidal and anything else: no simple public API, best-effort HTML scrape.
    title = _scrape_title(url)
    if not title:
        raise RuntimeError(
            "No se pudo leer el título de esta pista para buscarla en YouTube/SoundCloud."
        )
    return title


def resolve_foreign_track(url: str) -> list[dict]:
    """Best-effort match: reads the track's title/artist and searches both
    YouTube and SoundCloud (not just one — YouTube is increasingly prone to
    blocking datacenter IPs with its anti-bot check, so having a SoundCloud
    candidate ready to fall back to at download time matters). Returns a
    list of {"url", "title"} candidates, YouTube first if found, or raises
    if neither turned up anything."""
    query = _fetch_query(url)

    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "socket_timeout": 20,
        "retries": 3,
    }
    candidates = []
    for search_prefix in ("ytsearch1", "scsearch1"):
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f"{search_prefix}:{query}", download=False)
            entries = info.get("entries") or []
            if entries and entries[0]:
                found = entries[0]
                found_url = found.get("url") or found.get("webpage_url")
                if found_url:
                    candidates.append({"url": found_url, "title": found.get("title") or query})
        except Exception:  # noqa: BLE001
            continue

    if not candidates:
        raise RuntimeError(f'No se encontró "{query}" en YouTube ni SoundCloud.')
    return candidates
