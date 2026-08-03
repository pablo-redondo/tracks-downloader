"""Best-effort BPM/key estimation for organizing a DJ library."""
from __future__ import annotations

import numpy as np
import librosa
from mutagen.id3 import ID3, TBPM, TKEY
from mutagen.mp3 import MP3

_PITCH_CLASSES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Krumhansl-Schmuckler key profiles
_MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_MINOR_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

# Standard Camelot wheel, indexed by pitch class (0=C ... 11=B)
_CAMELOT_MAJOR = ["8B", "3B", "10B", "5B", "12B", "7B", "2B", "9B", "4B", "11B", "6B", "1B"]
_CAMELOT_MINOR = ["5A", "12A", "7A", "2A", "9A", "4A", "11A", "6A", "1A", "8A", "3A", "10A"]


def _estimate_key(y: np.ndarray, sr: int) -> tuple[str, str]:
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr).mean(axis=1)
    best_score = -np.inf
    best_pitch = 0
    best_major = True
    for shift in range(12):
        major_score = np.corrcoef(np.roll(_MAJOR_PROFILE, shift), chroma)[0, 1]
        minor_score = np.corrcoef(np.roll(_MINOR_PROFILE, shift), chroma)[0, 1]
        if major_score > best_score:
            best_score, best_pitch, best_major = major_score, shift, True
        if minor_score > best_score:
            best_score, best_pitch, best_major = minor_score, shift, False

    name = _PITCH_CLASSES[best_pitch]
    if best_major:
        return f"{name} mayor", _CAMELOT_MAJOR[best_pitch]
    return f"{name} menor", _CAMELOT_MINOR[best_pitch]


def analyze_audio(path: str) -> dict:
    """Loads (at most) the first 2 minutes of the track to estimate BPM and key."""
    y, sr = librosa.load(path, sr=22050, mono=True, duration=120)
    tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
    bpm = float(np.atleast_1d(tempo)[0])
    key_label, camelot = _estimate_key(y, sr)
    return {"bpm": round(bpm, 1), "key": key_label, "camelot": camelot}


def tag_analysis(path: str, bpm: float, camelot: str) -> None:
    audio = MP3(path, ID3=ID3)
    if audio.tags is None:
        audio.add_tags()
    audio.tags.add(TBPM(encoding=3, text=str(round(bpm))))
    audio.tags.add(TKEY(encoding=3, text=camelot))
    audio.save()
