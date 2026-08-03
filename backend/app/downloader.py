"""Job manager: extracts track/playlist info with yt-dlp and downloads audio
from YouTube and SoundCloud only."""
from __future__ import annotations

import shutil
import threading
import time
import uuid
import zipfile
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yt_dlp

from .analysis import analyze_audio, tag_analysis

BASE_DIR = Path(__file__).resolve().parent.parent
DOWNLOADS_DIR = BASE_DIR / "downloads"
DOWNLOADS_DIR.mkdir(exist_ok=True)

ALLOWED_DOMAINS = (
    "youtube.com",
    "youtu.be",
    "music.youtube.com",
    "soundcloud.com",
    "on.soundcloud.com",
    "soundcloud.app.goo.gl",
)

# Downloading is mostly network-bound (yt-dlp resolving the stream + the
# transfer itself), so it scales well beyond the machine's CPU count.
_ITEM_WORKERS = 5


class _RateLimiter:
    """Sliding-window limiter: blocks callers so no more than `max_calls`
    happen within any `period` seconds, shared across every thread that
    calls it."""

    def __init__(self, max_calls: int, period: float) -> None:
        self._max_calls = max_calls
        self._period = period
        self._lock = threading.Lock()
        self._calls: deque = deque()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                while self._calls and now - self._calls[0] > self._period:
                    self._calls.popleft()
                if len(self._calls) < self._max_calls:
                    self._calls.append(now)
                    return
                sleep_for = self._period - (now - self._calls[0]) + 0.05
            time.sleep(max(sleep_for, 0.05))


def _is_soundcloud(url: str) -> bool:
    return "soundcloud.com" in url or "soundcloud.app.goo.gl" in url


# SoundCloud's public API allows ~600 requests per 10 minutes; blow past it
# and it 429s almost everything for the rest of that window, which looks
# like the app being frozen (it isn't — SoundCloud is refusing us). Staying
# comfortably under that ceiling means downloads keep flowing steadily
# instead of bursting and then stalling for minutes at a time.
_SOUNDCLOUD_LIMITER = _RateLimiter(max_calls=450, period=600)


def _friendly_error(message: str) -> str:
    lowered = message.lower()
    if "go+" in lowered or "preview" in lowered and "soundcloud" in lowered:
        return "Esta pista es SoundCloud Go+ (de pago, con DRM) y no se puede descargar."
    if "private" in lowered and "token" in lowered:
        return "Pista privada: necesitas pegar el enlace completo con el token secreto que comparte el autor."
    if "geo" in lowered or "not available in your country" in lowered:
        return "Esta pista está bloqueada por región para tu ubicación."
    return message


@dataclass
class Item:
    id: str
    title: str
    source_url: str
    status: str = "pending"  # pending | downloading | completed | error
    progress: float = 0.0
    error: Optional[str] = None
    file_path: Optional[str] = None
    bpm: Optional[float] = None
    key: Optional[str] = None
    camelot: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "progress": round(self.progress, 1),
            "error": self.error,
            "bpm": self.bpm,
            "key": self.key,
            "camelot": self.camelot,
        }


@dataclass
class Job:
    id: str
    url: str
    quality: str
    title: str = ""
    is_playlist: bool = False
    status: str = "pending"  # pending | extracting | downloading | completed | completed_with_errors | error
    error: Optional[str] = None
    items: dict = field(default_factory=dict)
    item_order: list = field(default_factory=list)
    zip_completed_count: int = 0
    zip_lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def overall_progress(self) -> float:
        if not self.items:
            return 0.0
        return sum(i.progress for i in self.items.values()) / len(self.items)

    def to_dict(self) -> dict:
        items = []
        for item_id in self.item_order:
            item = self.items[item_id]
            data = item.to_dict()
            data["download_url"] = (
                f"/api/jobs/{self.id}/items/{item.id}/file" if item.status == "completed" else None
            )
            items.append(data)
        return {
            "id": self.id,
            "url": self.url,
            "quality": self.quality,
            "title": self.title,
            "is_playlist": self.is_playlist,
            "status": self.status,
            "error": self.error,
            "progress": round(self.overall_progress(), 1),
            "items": items,
        }


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        # BPM/key analysis (librosa/numba) runs on its own single-worker
        # queue, completely separate from the download workers. It used to
        # run inline behind a shared lock, which meant a single slow analysis
        # (e.g. numba's JIT warmup on first use) piled up every download
        # worker waiting on it — freezing the whole playlist after the first
        # _ITEM_WORKERS tracks. Decoupled, a slow analysis only delays BPM
        # tags, never downloads.
        self._analysis_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="analysis")

    def create_job(self, url: str, quality: str) -> str:
        job_id = uuid.uuid4().hex[:12]
        job = Job(id=job_id, url=url, quality=quality)
        with self._lock:
            self._jobs[job_id] = job
        threading.Thread(target=self._run_job, args=(job,), daemon=True).start()
        return job_id

    def get_job(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(self) -> list:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.id, reverse=True)
        return [j.to_dict() for j in jobs]

    def delete_job(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.pop(job_id, None)
        if job is None:
            return False
        shutil.rmtree(DOWNLOADS_DIR / job_id, ignore_errors=True)
        return True

    def build_zip(self, job_id: str) -> Optional[Path]:
        job = self.get_job(job_id)
        if job is None:
            return None
        completed = [i for i in job.items.values() if i.status == "completed" and i.file_path]
        if not completed:
            return None
        zip_path = DOWNLOADS_DIR / job_id / "_playlist.zip"
        with job.zip_lock:
            # Building the zip for a big playlist (hundreds of tracks) is slow
            # and doubles disk usage momentarily; skip it if nothing changed
            # since the last time it was built (usually nothing — items get
            # appended incrementally as they finish, see _append_to_zip).
            if zip_path.exists() and job.zip_completed_count == len(completed):
                return zip_path
            # mp3 is already compressed, so ZIP_STORED (no re-compression)
            # is just as small and much faster than ZIP_DEFLATED here.
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zf:
                for item in completed:
                    zf.write(item.file_path, arcname=Path(item.file_path).name)
            job.zip_completed_count = len(completed)
            return zip_path

    # -- internals ---------------------------------------------------

    def _run_job(self, job: Job) -> None:
        job.status = "extracting"
        try:
            entries = self._extract_entries(job.url)
        except Exception as exc:  # noqa: BLE001
            job.status = "error"
            job.error = f"No se pudo leer el enlace: {exc}"
            return

        if not entries:
            job.status = "error"
            job.error = "El enlace no contiene pistas descargables"
            return

        job.is_playlist = len(entries) > 1
        job.title = entries[0].get("playlist_title") or entries[0]["title"]

        for idx, entry in enumerate(entries):
            item_id = str(idx)
            job.items[item_id] = Item(id=item_id, title=entry["title"], source_url=entry["url"])
            job.item_order.append(item_id)

        job.status = "downloading"
        job_dir = DOWNLOADS_DIR / job.id
        job_dir.mkdir(parents=True, exist_ok=True)

        with ThreadPoolExecutor(max_workers=_ITEM_WORKERS) as pool:
            list(pool.map(lambda item_id: self._download_item(job, job.items[item_id], job_dir), job.item_order))

        statuses = {i.status for i in job.items.values()}
        if statuses == {"completed"}:
            job.status = "completed"
        elif "completed" in statuses:
            job.status = "completed_with_errors"
        else:
            job.status = "error"
            job.error = "No se pudo descargar ningún elemento"

    def _extract_entries(self, url: str) -> list[dict]:
        opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": "in_playlist",
            "skip_download": True,
            "socket_timeout": 30,
            "retries": 5,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)

        entries_raw = info.get("entries")
        results = []
        if entries_raw:
            for entry in entries_raw:
                if not entry:
                    continue
                track_url = entry.get("url") or entry.get("webpage_url")
                if not track_url:
                    continue
                results.append(
                    {
                        "url": track_url,
                        "title": entry.get("title") or "audio",
                        "playlist_title": info.get("title"),
                    }
                )
        else:
            results.append(
                {
                    "url": info.get("webpage_url") or url,
                    "title": info.get("title") or "audio",
                    "playlist_title": None,
                }
            )
        return results

    def _download_item(self, job: Job, item: Item, job_dir: Path) -> None:
        if _is_soundcloud(item.source_url):
            # Stays "pending" (not "downloading") while it waits its turn —
            # it's genuinely not started yet, just paced to respect
            # SoundCloud's rate limit instead of getting 429'd.
            _SOUNDCLOUD_LIMITER.acquire()
        item.status = "downloading"
        index = job.item_order.index(item.id) + 1
        prefix = f"{index:02d} - " if job.is_playlist else ""
        outtmpl = str(job_dir / f"{prefix}%(title)s.%(ext)s")

        def hook(d: dict) -> None:
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                downloaded = d.get("downloaded_bytes", 0)
                if total:
                    item.progress = min(95.0, downloaded / total * 95)
            elif d.get("status") == "finished":
                item.progress = 97.0

        opts = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "format": "bestaudio/best",
            "outtmpl": outtmpl,
            "progress_hooks": [hook],
            "postprocessors": [
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": job.quality},
                {"key": "FFmpegMetadata", "add_metadata": True},
                {"key": "EmbedThumbnail"},
            ],
            "writethumbnail": True,
            # Bounded so a single rate-limited/stalled track can't hog a
            # worker thread forever — with only _ITEM_WORKERS threads, a
            # handful of stuck items is enough to stall an entire playlist.
            # Better to fail that one item fast and move on to the rest.
            "socket_timeout": 30,
            "retries": 5,
            "fragment_retries": 5,
            "extractor_retries": 3,
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(item.source_url, download=True)
                filename = ydl.prepare_filename(info)
                mp3_path = str(Path(filename).with_suffix(".mp3"))
            if not Path(mp3_path).exists():
                raise RuntimeError("La conversión a mp3 falló")
            item.file_path = mp3_path
            item.progress = 100.0
            item.status = "completed"
        except Exception as exc:  # noqa: BLE001
            item.status = "error"
            item.error = _friendly_error(str(exc))
            return

        # BPM/key analysis + adding the file to the playlist zip both happen
        # in the background: the download worker returns immediately, ready
        # to pick up the next track, instead of waiting on either of them.
        self._analysis_executor.submit(self._finish_item, job, item, mp3_path)

    def _finish_item(self, job: Job, item: Item, mp3_path: str) -> None:
        # Best-effort BPM/key analysis: never fail the download over this.
        try:
            result = analyze_audio(mp3_path)
            item.bpm = result["bpm"]
            item.key = result["key"]
            item.camelot = result["camelot"]
            tag_analysis(mp3_path, result["bpm"], result["camelot"])
        except Exception:  # noqa: BLE001
            pass

        if job.is_playlist:
            self._append_to_zip(job, item)

    def _append_to_zip(self, job: Job, item: Item) -> None:
        """Adds a finished track to the playlist zip as soon as it's ready,
        so the zip is already built (or nearly) by the time the job
        finishes — no need to compress hundreds of tracks in one go when
        the user (or the auto-download) requests it."""
        zip_path = DOWNLOADS_DIR / job.id / "_playlist.zip"
        try:
            with job.zip_lock:
                mode = "a" if zip_path.exists() else "w"
                with zipfile.ZipFile(zip_path, mode, zipfile.ZIP_STORED) as zf:
                    zf.write(item.file_path, arcname=Path(item.file_path).name)
                job.zip_completed_count += 1
        except Exception:  # noqa: BLE001
            pass
