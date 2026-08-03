# Tracks Downloader

Aplicación web local para descargar canciones sueltas o playlists completas
de **YouTube** y **SoundCloud** en mp3, pensada para armar tu librería de DJ.

## Requisitos

- Python 3.10+
- [ffmpeg](https://ffmpeg.org/) instalado y en el `PATH` (necesario para
  convertir a mp3 e incrustar carátula/metadatos)
  - Debian/Ubuntu: `sudo apt install ffmpeg`
  - macOS: `brew install ffmpeg`

## Puesta en marcha

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Abre [http://localhost:8000](http://localhost:8000).

## Uso

1. Pega el enlace de una canción o una playlist de YouTube o SoundCloud.
2. Elige la calidad (128 / 192 / 320 kbps).
3. Pulsa "Descargar". Verás el progreso de cada pista en tiempo real.
4. Cuando termine, descarga cada mp3 individualmente o, si era una
   playlist, todo junto en un ZIP.

Los mp3 se guardan (mientras el proceso está en marcha) en
`backend/downloads/<job_id>/`, con metadatos y carátula incrustados.

## Alcance

Solo admite enlaces de `youtube.com`, `youtu.be`, `music.youtube.com`,
`soundcloud.com` y `on.soundcloud.com`. Otras plataformas (Spotify, Apple
Music, etc.) no están soportadas porque protegen su audio con DRM.
