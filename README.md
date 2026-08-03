# Tracks Downloader

Aplicación web para descargar canciones sueltas o playlists completas de
**YouTube** y **SoundCloud** en mp3, con BPM y tonalidad (Camelot) estimados
automáticamente para organizar tu librería de DJ.

## Arquitectura

- `backend/` — FastAPI + `yt-dlp` + `ffmpeg` + `librosa`. Descarga, convierte
  a mp3, analiza BPM/tonalidad y etiqueta el archivo (ID3 `TBPM`/`TKEY`).
  Necesita un proceso de larga duración con disco, así que **no puede
  desplegarse en Vercel** (funciones serverless, sin ffmpeg, sin disco
  persistente). Despliégalo en un VPS o en un servicio con capa gratuita que
  soporte contenedores/procesos largos: Railway, Render, Fly.io, tu propio
  servidor, etc.
- `frontend/` — HTML/CSS/JS estático sin build, listo para desplegar en
  **Vercel** como proyecto independiente. Habla con el backend por HTTPS
  (CORS ya está habilitado en el backend).

## Backend: puesta en marcha local

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Requiere [ffmpeg](https://ffmpeg.org/) instalado (`apt install ffmpeg` /
`brew install ffmpeg`).

Con esto abierto en `http://localhost:8000` ya sirve también el frontend
integrado (no hace falta Vercel para uso local).

### Desplegar el backend (para poder usarlo desde el frontend en Vercel)

Cualquier host que permita Docker/Python de larga duración con ffmpeg vale.
Por ejemplo con Railway o Render:

1. Conecta este repo, configura el **Root Directory** en `backend`.
2. Build command: `pip install -r requirements.txt`
3. Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
4. Asegúrate de que la imagen tenga `ffmpeg` (en Railway/Render con buildpacks
   Nix/Docker basta con añadir el paquete `ffmpeg`; con Docker propio,
   `apt-get install -y ffmpeg` en el Dockerfile).
5. Anota la URL pública HTTPS que te den (p. ej. `https://tu-app.up.railway.app`).

## Frontend: desplegar en Vercel

1. En [vercel.com](https://vercel.com), "Add New Project" → importa este
   repo de GitHub (`pablo-redondo/tracks-downloader`).
2. **Root Directory**: `frontend`
3. **Framework Preset**: "Other" (es HTML/JS estático, sin build).
4. Deploy.
5. Abre la URL que te da Vercel, pulsa el botón **⚙️ Backend** de la
   cabecera y pega la URL pública de tu backend (paso anterior). Se guarda
   en el navegador (localStorage), solo hace falta una vez.

## Uso

1. Pega el enlace de una canción o una playlist de YouTube o SoundCloud.
2. Elige la calidad (128 / 192 / 320 kbps).
3. Pulsa "Descargar". Verás el progreso de cada pista en tiempo real, y al
   terminar el BPM y la tonalidad (notación Camelot, p. ej. `8A`) estimados.
4. Descarga cada mp3 individualmente o, si era una playlist, todo junto en
   un ZIP.

Los mp3 se guardan (mientras el proceso está en marcha) en
`backend/downloads/<job_id>/`, con metadatos, carátula, BPM y tonalidad ya
incrustados en las etiquetas ID3 — listos para importar en Rekordbox,
Serato, Traktor, etc.

## Alcance

Solo admite enlaces de `youtube.com`, `youtu.be`, `music.youtube.com`,
`soundcloud.com`, `soundcloud.app.goo.gl` y `on.soundcloud.com`.

- La inmensa mayoría de pistas públicas de SoundCloud se descargan sin
  problema, tengan o no el botón de "descarga" activado por el autor
  (`yt-dlp` obtiene el audio directamente del streaming, no de ese botón).
- Pistas **privadas**: pega el enlace completo con el token secreto que te
  pase el autor.
- Pistas **SoundCloud Go+** (de pago, protegidas con DRM) no se pueden
  descargar — la app te lo indicará como error.
- Spotify y Apple Music no están soportados porque protegen su audio con
  DRM.

## BPM y tonalidad

Se estiman de forma local con `librosa` (analizando los primeros 2 minutos
de cada pista) y son **aproximados** — pensados para tener una referencia
rápida al organizar tu librería, no para sustituir un análisis fino tipo
Mixed In Key.
