# WAVIFY — Auditoría e informe de viabilidad

## 1. Auditoría del entorno y del proyecto (fase 1)

| Elemento | Estado |
|---|---|
| Repositorio | Contiene *Spotify to WAV Converter* (app de escritorio Electron + FastAPI). Es otro producto: **no se elimina**. WAVIFY se crea en `wavify/` como proyecto independiente. |
| Python 3.13, FastAPI, httpx, mutagen | Disponibles |
| FFmpeg 6.1 (libmp3lame) | Disponible: conversión MP3 viable en el backend |
| Node 22, npm | Disponibles. Último Expo publicado: **SDK 58** (react-native 0.88) |
| Red saliente | **Solo npm y PyPI.** La política de red de la sesión deniega (HTTP 403) `api.spotify.com`, `accounts.spotify.com`, `open.spotify.com`, `api.jamendo.com`, `archive.org`, `freemusicarchive.org`, `ccmixter.org`, `api.audius.co`. |
| Credenciales | Ninguna configurada (Spotify, Jamendo). |

Consecuencia: los adaptadores se implementan según la documentación pública oficial, pero **no se han podido verificar con
peticiones reales desde esta sesión**. El proyecto incluye `scripts/verify_live.py` y pruebas `-m live` para verificarlos en
cuanto haya red y credenciales. Nada de lo anterior se presenta como resultado real.

## 2. Viabilidad por componente

| Componente | Viable | Notas |
|---|---|---|
| Identificar enlaces de Spotify | Sí | Web API `GET /v1/tracks/{id}` con *Client Credentials* (no requiere login del usuario). Requiere `SPOTIFY_CLIENT_ID` y `SPOTIFY_CLIENT_SECRET` en el servidor. Spotify **no** entrega audio descargable: solo metadatos. Algunos campos (p. ej. ISRC) pueden no estar disponibles según el modo de la app; el código los trata como opcionales. |
| Internet Archive | Sí, sin clave | `advancedsearch.php` + `/metadata/{id}` + `/download/{id}/{archivo}`. Solo se aceptan ítems con licencia declarada Creative Commons o dominio público y sin acceso restringido. |
| Jamendo | Sí, con clave gratuita | API v3.0 (`/tracks`), requiere `JAMENDO_CLIENT_ID`. Expone `audiodownload_allowed` y la licencia CC de cada pista. |
| Free Music Archive | **No integrado** | No hay una API pública documentada y verificable actualmente; descargar desde la web sería *scraping*. |
| Tiendas (Bandcamp, Qobuz, 7digital, Amazon…) | **No integrado** | No ofrecen API pública de descarga; requieren acuerdos comerciales. El estado «Requiere compra» está previsto en la arquitectura. |
| Conversión MP3 128–320 kbps | Sí | FFmpeg/libmp3lame en el backend. Nunca se «sube» la calidad: si el origen es MP3 de menor tasa se informa la tasa real. |
| App móvil (Expo Go) | Sí | Expo SDK 58 + Expo Router + TypeScript; guardado con `expo-file-system` + `expo-sharing` (compatibles con Expo Go). |

## 3. Limitación principal (importante)

Las fuentes legales integrables alojan sobre todo **música independiente con licencias abiertas**. La gran mayoría de las
canciones comerciales de Spotify **no tienen ninguna versión descargable autorizada** en esas fuentes. Para esas canciones
WAVIFY informará con claridad «No hay una versión descargable autorizada», que es el comportamiento correcto. Los aciertos
se producirán con artistas que publican tanto en Spotify como en Jamendo/Internet Archive con licencia libre.

## 4. Plan de implementación

1. Backend FastAPI: parser de enlaces, cliente Spotify, interfaz `AudioProvider`, registro de proveedores, búsqueda paralela
   (timeouts, reintentos, caché, deduplicación, pausa de proveedores caídos), motor de coincidencias, motor de descarga
   autorizada, conversión MP3 verificada, trabajos con estados/cancelación y limpieza de temporales, límite de peticiones.
2. App Expo de una pantalla con los 11 estados.
3. Pruebas: unitarias e integración (simulaciones solo en tests), conversión real con FFmpeg, E2E de la interfaz.
4. Verificación en vivo (`scripts/verify_live.py`) cuando la red y las credenciales estén disponibles.

## 5. Estado de verificación (al cierre de esta sesión)

| Qué | Verificado | Cómo |
|---|---|---|
| Motor completo (enlace → coincidencia → licencias → descarga → MP3) | Sí | 70 pruebas del backend con FFmpeg real; los servicios externos se simulan en los tests |
| App móvil (estados, guardado, errores, cancelación) | Sí | 24 pruebas Jest y E2E en Chromium sobre el build web de Expo contra el backend |
| Spotify Web API real | **No** | La red de la sesión deniega `api.spotify.com` y `accounts.spotify.com`, y no hay credenciales |
| Internet Archive real | **No** | La red de la sesión deniega `archive.org` (`pytest -m live` falla por la red) |
| Jamendo real | **No** | La red deniega `api.jamendo.com` y falta `JAMENDO_CLIENT_ID` |
| App en un iPhone o Android físico | **No** | No hay dispositivo; el código usa solo módulos incluidos en Expo Go |

Siguiente paso: habilitar esos dominios y credenciales y ejecutar `pytest -m live` y `scripts/verify_live.py`.
