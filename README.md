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

Hay dos Dockerfiles preparados porque el repo también tiene `frontend/` —
uno para usar la CLI de Fly desde `backend/`, y otro en la raíz por si usas
el asistente web de Fly (que solo detecta un Dockerfile en la raíz del
repo). Usa el que encaje con cómo quieras desplegar; el resultado es el
mismo backend.

#### Opción A: CLI de Fly (recomendada)

Usa `backend/Dockerfile` y `backend/fly.toml`. Necesitas la
[CLI de Fly](https://fly.io/docs/flyctl/install/) y una cuenta (pide
tarjeta para verificar, no cobra dentro del free tier):

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

#### Opción B: asistente web de Fly (Dockerfile en la raíz)

Si conectas el repo desde [fly.io/dashboard](https://fly.io/dashboard) y
usas su asistente de "Launch", este solo mira un Dockerfile en la raíz del
repositorio. Para ese flujo están `Dockerfile` y `fly.toml` en la raíz
(no en `backend/`) — con las mismas rutas pero copiando desde
`backend/requirements.txt` y `backend/app`. No hace falta que hagas nada
distinto: el asistente lo detectará solo y podrás seguir con "Deploy".

Importante en ambas opciones — el estado de los trabajos vive en memoria
del proceso, así que **no escales a más de 1 máquina**
(`fly scale count 1`, que además es el valor por defecto). Los `fly.toml`
ya fijan `min_machines_running = 1` y `auto_stop_machines = false` para que
la app no se "duerma" a mitad de una descarga.

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

## Playlists grandes (cientos de pistas)

La app está pensada para poder pegar una playlist entera (aunque tenga
cientos de canciones) y que se descargue sola:

- Las descargas van en paralelo (3 a la vez) pero el análisis de BPM/tonalidad
  (lo más pesado en memoria, por `librosa`/`numba`) se serializa a 1 pista a
  la vez, para no disparar el consumo de RAM con listas largas.
- El ZIP de "descargar todo" se cachea: si ya estaba construido y no hay
  pistas nuevas completadas, no se reconstruye desde cero cada vez que se
  pide.
- El frontend actualiza solo las filas que cambiaron en cada sondeo (en vez
  de redibujar la lista entera) y espacia el intervalo de sondeo según el
  tamaño de la lista (hasta cada 4s con más de 200 pistas), para no ir lento
  en listas de 500+.

Recomendaciones si vas a mover playlists muy grandes (según la máquina de
Fly.io que tengas):

- **Memoria**: los `fly.toml` de este repo ya piden `2048mb` (antes 1024mb).
  Si tu app ya estaba desplegada con 1024mb, súbela con
  `fly scale memory 2048` (CLI) o redeploy con el `fly.toml` actualizado.
- **Disco**: 500 pistas a 320 kbps son varios GB (los mp3 se quedan en
  `backend/downloads/<job_id>/` hasta que borres el job). El ZIP añade
  temporalmente casi el mismo tamaño otra vez mientras se genera. Si tu
  máquina de Fly se queda sin disco, para playlists enormes es más seguro
  descargar los mp3 sueltos en vez del ZIP, o borrar el job
  (`DELETE /api/jobs/<job_id>`) tras descargar antes de lanzar la siguiente
  tanda grande.
- **Rate limit de SoundCloud**: su API pública admite ~600 peticiones cada
  10 minutos. Con 500 pistas de SoundCloud puedes rozar ese límite; si ves
  errores puntuales de "rate limit" en algunas pistas, reinténtalas más
  tarde — `yt-dlp` ya reintenta automáticamente varias veces antes de darse
  por vencido.
