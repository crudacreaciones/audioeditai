# WAVIFY

*Tu música, lista para llevar.* App móvil (iOS/Android, Expo) que recibe un enlace de Spotify, identifica la canción y busca
en paralelo en **fuentes que autorizan la descarga** una versión que sea, con seguridad, la misma grabación. Si existe, la
descarga por el mecanismo oficial de la fuente, la convierte a MP3 y permite guardarla en el dispositivo. Si no existe, lo dice
claramente y no descarga nada.

> WAVIFY **no** descarga audio de Spotify, no elude DRM, no hace *scraping* y no usa servicios de «descarga de Spotify».
> Spotify solo se usa para leer los metadatos de la canción.

Informe de viabilidad y limitaciones: [`docs/VIABILIDAD.md`](docs/VIABILIDAD.md).

## Arquitectura

```
mobile/  (Expo SDK 58 · Expo Router · TypeScript)       backend/  (Python · FastAPI · FFmpeg)
 una pantalla, 11 estados                  HTTPS          api.py        /api/v1/jobs, /providers, /health
 POST /jobs → sondeo del estado  ───────────────────────► jobs.py       pipeline por etapas, cancelación, TTL
 GET /jobs/{id}/file → guardar                            spotify.py    enlaces + Web API (Client Credentials)
 expo-file-system / expo-sharing                          search.py     búsqueda paralela: timeouts, reintentos,
                                                                        caché, deduplicación, pausa de caídos
                                                          matching.py   identidad de grabación (versión, ISRC…)
                                                          providers/    AudioProvider + registro (plug-ins)
                                                            internet_archive.py · jamendo.py · licenses.py
                                                          downloader.py descarga autorizada (dominios, MD5, tamaño)
                                                          converter.py  MP3 128–320 kbps, verificación, metadatos
```

### Pipeline
1. **Analizar enlace** (`open.spotify.com/track/…`, `intl-xx`, `spotify:track:…`, `spotify.link`/`spoti.fi`; rechaza álbumes, playlists, etc.).
2. **Identificar** con Spotify Web API: título, artistas, álbum, portada, duración, ID, enlace e ISRC si está disponible.
3. **Buscar** a la vez en todos los proveedores activos. Un proveedor caído o lento no detiene a los demás.
4. **Comparar**. Para aceptar un resultado sin ISRC deben coincidir: el tipo de versión (original, remasterización, directo,
   remix, instrumental, cover u otra), un título ≥ 0,92, el artista principal ≥ 0,85, una duración conocida a ±max(3 s, 2 %) y
   una puntuación ≥ 0,85. Un ISRC igual confirma la coincidencia y uno distinto la descarta.
5. **Comprobar permisos**: la licencia y la disponibilidad las declara la propia fuente. Cada resultado queda en uno de
   estos estados: *Descargable*, *Requiere compra o autorización*, *Solo reproducción*, *Licencia incompatible*,
   *No disponible* o *Coincidencia no verificada*.
6. **Descargar** solo resultados *Descargables*, desde los dominios de la fuente y por HTTPS (también en cada redirección), con
   límite de tamaño y verificación MD5 cuando la fuente la publica.
7. **Convertir** con FFmpeg/libmp3lame (320 kbps por defecto). La calidad nunca se infla: un MP3 de origen igual o inferior a
   la calidad pedida se conserva sin recodificar, y se avisa. El resultado se verifica con ffprobe y una decodificación
   completa. Lleva etiquetas ID3 con la fuente y la licencia (necesarias para la atribución CC).
8. **Archivo listo**: se descarga con un token de un solo trabajo. Los temporales se borran tras `WAVIFY_FILE_TTL` (30 min).

### Proveedores

| Proveedor | Estado | Credencial |
|---|---|---|
| Internet Archive | Implementado (advancedsearch, metadata y download). Solo ítems con licencia CC o de dominio público y sin préstamo. | Ninguna |
| Jamendo | Implementado (API v3.0, `audiodownload_allowed` y `license_ccurl`). | `JAMENDO_CLIENT_ID` (gratis en developer.jamendo.com) |
| Free Music Archive y tiendas | No integrados: no tienen una API pública de descarga verificable. | — |

Para añadir un proveedor, crea un módulo con una clase que implemente `AudioProvider` (`search`, `get_metadata`,
`check_availability`, `check_license`, `get_download`, `get_capabilities`, `health_check`) y añade `"modulo:Clase"` a
`WAVIFY_PROVIDERS`. El núcleo no cambia. Un proveedor solo aparece como `ok` tras una llamada real con éxito. Puede estar
`not_configured`, `disabled` o `down` (en pausa tras fallos seguidos).

## Puesta en marcha

### Backend
```bash
cd wavify/backend
pip install -r requirements.txt
export SPOTIFY_CLIENT_ID=...  SPOTIFY_CLIENT_SECRET=...   # developer.spotify.com/dashboard → Create app (Web API)
export JAMENDO_CLIENT_ID=...                               # opcional, developer.jamendo.com
python -m wavify --host 0.0.0.0 --port 8000
```
Requiere FFmpeg/FFprobe en el `PATH`. Todas las claves se guardan solo en el servidor; la app no contiene ningún secreto.

| Variable | Uso |
|---|---|
| `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET` | Identificar canciones (flujo Client Credentials; no hace falta que el usuario inicie sesión) |
| `JAMENDO_CLIENT_ID` | Activa el proveedor Jamendo |
| `WAVIFY_PROVIDERS`, `WAVIFY_DISABLED_PROVIDERS` | Lista de proveedores (`modulo:Clase`) y los que se desactivan |
| `WAVIFY_ADMIN_TOKEN` | Protege `POST /api/v1/providers/{id}/enable\|disable` y `/providers/check` |
| `WAVIFY_FILE_TTL`, `WAVIFY_JOBS_PER_MINUTE`, `WAVIFY_MAX_CONCURRENT_JOBS`, `WAVIFY_PROVIDER_TIMEOUT` | Límites |
| `WAVIFY_CORS_ORIGINS` | Solo para la versión web de desarrollo |

**HTTPS en producción**: pon el backend detrás de un proxy inverso con TLS (por ejemplo Caddy: `wavify.tudominio.com { reverse_proxy 127.0.0.1:8000 }`)
o usa `--ssl-certfile/--ssl-keyfile`. La app exige HTTPS salvo para direcciones locales de desarrollo.

### App móvil (Expo Go)
```bash
cd wavify/mobile
npm install
npx expo start                     # escanea el QR con Expo Go
# producción: EXPO_PUBLIC_API_URL=https://wavify.tudominio.com npx expo start
```
En desarrollo, la app usa automáticamente la IP del ordenador que sirve Expo (puerto 8000). Todo lo que usa la app
(`expo-file-system`, `expo-sharing`, `expo-clipboard`, `expo-router`) está incluido en Expo Go, así que no hace falta una
Development Build. Para guardar el archivo: en Android eliges una carpeta (Storage Access Framework); en iOS se abre la
hoja de compartir, desde donde se usa «Guardar en Archivos».

### Probar en un iPhone con Expo Go
1. Instala **Expo Go** desde la App Store (debe admitir el **SDK 58**; si dice «Project is incompatible with this version of Expo Go», actualízala).
2. En tu ordenador, con el iPhone en la **misma Wi-Fi**:
   ```bash
   cd wavify/backend && python -m wavify --host 0.0.0.0 --port 8000     # backend (necesita las credenciales de Spotify)
   cd wavify/mobile && npm install && npx expo start --go                # muestra un QR y un enlace exp://<IP>:8081
   ```
3. Escanea el QR con la **Cámara** del iPhone y ábrelo en Expo Go. Acepta el permiso de **Red local** que pide iOS.
4. Si tu red no permite la conexión directa, usa el túnel: `npx expo login` y después `npx expo start --tunnel`.
   Sin cuenta de Expo puedes usar `npx expo start --tunnel ngrok` (antes, `npm i -g @expo/ngrok`).

La app usa automáticamente `http://<IP del ordenador>:8000` como backend. Con un backend publicado, define
`EXPO_PUBLIC_API_URL=https://…` antes de `npx expo start`.

## Pruebas

```bash
cd wavify/backend && python -m pytest          # 70 pruebas (FFmpeg real; servicios externos simulados SOLO en tests)
cd wavify/mobile && npm run typecheck && npx jest   # 24 pruebas de la app
wavify/e2e/run.sh /tmp/wavify-e2e               # E2E en Chromium: build web de Expo + backend real + FFmpeg real
```

Las simulaciones (`backend/tests/fakes.py`, `backend/tests/e2e_server.py`, `mobile/test-support/`) solo existen para las
pruebas. **Sus resultados no son resultados de búsqueda reales.**

### Verificación con los servicios reales
Requiere acceso de red a esos dominios y las credenciales.
```bash
cd wavify/backend
python -m pytest -m live
python scripts/verify_live.py "https://open.spotify.com/track/<id>"
```
`verify_live.py` muestra el estado real de cada proveedor y el recorrido completo de cada enlace: la canción identificada,
los candidatos con su estado y la ruta del MP3 si se ha generado.
