# Tracks Downloader

Aplicación web para descargar canciones sueltas o playlists completas de
**YouTube** y **SoundCloud** en mp3, con BPM y tonalidad (Camelot) estimados
automáticamente para organizar tu librería de DJ.

## Arquitectura

- `backend/` — FastAPI + `yt-dlp` + `ffmpeg` + `librosa`. Descarga, convierte
  a mp3, analiza BPM/tonalidad y etiqueta el archivo (ID3 `TBPM`/`TKEY`).
  Necesita un proceso de larga duración con disco, así que **no puede
  desplegarse en Vercel** (funciones serverless, sin ffmpeg, sin disco
  persistente) ni en plataformas que "congelan" la CPU entre peticiones
  (Cloud Run, etc.) — las descargas siguen en un hilo en segundo plano
  después de responder al request. Este repo ya trae `Dockerfile` y
  `fly.toml` listos para **Fly.io** (ver más abajo).
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

### Desplegar el backend en Fly.io

`backend/Dockerfile` (Python 3.11 + ffmpeg + libsndfile) y `backend/fly.toml`
ya están preparados. Solo te hace falta la [CLI de Fly](https://fly.io/docs/flyctl/install/)
y una cuenta (pide tarjeta para verificar, no cobra dentro del free tier):

```bash
cd backend
fly auth login
fly launch --no-deploy   # detecta el Dockerfile; te pedirá nombre de app y región
                          # (puedes aceptar sobrescribir fly.toml con tus datos)
fly deploy
```

Si prefieres no usar `fly launch`, edita el nombre de `app` dentro de
`backend/fly.toml` por algo único tuyo, luego:

```bash
fly apps create tu-nombre-unico
fly deploy
```

Importante — el estado de los trabajos vive en memoria del proceso, así que
**no escales a más de 1 máquina** (`fly scale count 1`, que además es el
valor por defecto). `fly.toml` ya fija `min_machines_running = 1` y
`auto_stop_machines = false` para que la app no se "duerma" a mitad de una
descarga.

Cuando termine el deploy, `fly status` te da la URL pública
(`https://tu-nombre-unico.fly.dev`).

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
