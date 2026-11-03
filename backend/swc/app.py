"""Service container + FastAPI application."""
from __future__ import annotations

import json
import os
import string
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import (APP_NAME, APP_VERSION, AUDIO_EXTENSIONS, BIT_DEPTHS, CHANNEL_OPTIONS, DEFAULT_SETTINGS,
                     SAMPLE_RATES, AppConfig, load_config)
from .db import Database
from .oplog import OpLog, setup_file_logging
from .services.audio import AudioError, FFmpeg, WavSpec
from .services.converter import ConversionManager
from .services.exporter import Exporter
from .services.library import Library
from .services.matcher import Matcher
from .services.spotify import NotConnected, SpotifyClient, SpotifyError

FRONTEND_DIR = Path(os.environ.get("SWC_FRONTEND_DIR") or Path(__file__).resolve().parents[2] / "frontend")


class Services:
    """Wires every service together; one instance per running app."""

    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self.log_file = setup_file_logging(cfg.log_dir)
        self.db = Database(cfg.db_path)
        self.log = OpLog(self.db)
        self.ff = FFmpeg(cfg.ffmpeg, cfg.ffprobe)
        self.library = Library(self.db, self.ff, self.log)
        self.converter = ConversionManager(self.db, self.ff, self.log, self.settings)
        self.exporter = Exporter(self.db, self.log)
        self.matcher = Matcher(self.db, self.log)
        self.spotify = SpotifyClient(self.db, self.log, cfg.spotify_accounts_url, cfg.spotify_api_url, self.settings)

    def settings(self) -> dict:
        out = dict(DEFAULT_SETTINGS)
        for k in DEFAULT_SETTINGS:
            v = self.db.get_setting(k)
            if v is not None:
                out[k] = v
        out["output_dir"] = out["output_dir"] or str(self.cfg.default_output_dir)
        out["spotify_redirect_uri"] = out["spotify_redirect_uri"] or self.cfg.default_redirect_uri
        return out

    def update_settings(self, values: dict) -> dict:
        for k, v in values.items():
            if k not in DEFAULT_SETTINGS:
                continue
            if k == "default_sample_rate" and int(v) not in SAMPLE_RATES:
                raise ValueError("Frecuencia no soportada")
            if k == "default_bit_depth" and str(v) not in BIT_DEPTHS:
                raise ValueError("Profundidad no soportada")
            if k == "default_channels" and int(v) not in CHANNEL_OPTIONS:
                raise ValueError("Canales no soportados")
            if k == "concurrency":
                v = max(1, min(8, int(v)))
            if k == "output_dir" and v:
                Path(v).expanduser().mkdir(parents=True, exist_ok=True)
            self.db.set_setting(k, v)
        self.log.info("settings", "Configuración actualizada", {k: v for k, v in values.items() if k in DEFAULT_SETTINGS})
        return self.settings()

    def start(self) -> None:
        self.converter.start()
        info = self.ff.available()
        if not info["ffmpeg"] or not info["ffprobe"]:
            self.log.error("system", "FFmpeg/FFprobe no encontrados. Instálalos y reinicia la aplicación.")
        self.log.info("system", f"{APP_NAME} {APP_VERSION} iniciado", {"data_dir": str(self.cfg.data_dir)})

    def stop(self) -> None:
        self.converter.stop()


# ---- request models ----------------------------------------------------
class ImportRequest(BaseModel):
    paths: list[str]
    recursive: bool = True
    skip_duplicates: bool | None = None


class ConvertRequest(BaseModel):
    track_ids: list[int] = Field(default_factory=list)
    sample_rate: int = 44100
    bit_depth: str = "16"
    channels: int = 2
    output_dir: str | None = None
    naming_pattern: str | None = None


class ExportRequest(BaseModel):
    conversion_ids: list[int]
    dest_dir: str
    naming_pattern: str | None = None
    overwrite: bool = False


class MetadataRequest(BaseModel):
    values: dict[str, Any]
    write_to_file: bool = False


class IdsRequest(BaseModel):
    ids: list[Any]


def create_app(cfg: AppConfig | None = None, start_workers: bool = True) -> FastAPI:
    cfg = cfg or load_config()
    svc = Services(cfg)

    @asynccontextmanager
    async def lifespan(_app):
        if start_workers:
            svc.start()
        yield
        svc.stop()

    app = FastAPI(title=APP_NAME, version=APP_VERSION, lifespan=lifespan)
    app.state.svc = svc

    allowed_hosts = {"127.0.0.1", "localhost", "testserver", "[::1]"}

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        # Defend the local API against DNS rebinding and cross-site requests from web pages.
        host = _hostname(request.headers.get("host") or "")
        if host not in allowed_hosts:
            return JSONResponse({"detail": "Host no permitido"}, status_code=403)
        if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("x-swc") != "1":
            return JSONResponse({"detail": "Cabecera X-SWC requerida"}, status_code=403)
        return await call_next(request)

    @app.exception_handler(SpotifyError)
    async def spotify_error(_req, exc: SpotifyError):
        code = 401 if isinstance(exc, NotConnected) else (exc.status if 400 <= exc.status < 600 else 502)
        return JSONResponse({"detail": str(exc)}, status_code=code)

    @app.exception_handler(AudioError)
    async def audio_error(_req, exc: AudioError):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(ValueError)
    async def value_error(_req, exc: ValueError):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    # ---- system ----------------------------------------------------------
    @app.get("/api/health")
    def health():
        return {"ok": True, "app": APP_NAME, "version": APP_VERSION}

    @app.get("/api/system")
    def system():
        return {
            "app": APP_NAME, "version": APP_VERSION, "python": sys.version.split()[0], "platform": sys.platform,
            "ffmpeg": svc.ff.available(), "data_dir": str(cfg.data_dir), "db_path": str(cfg.db_path),
            "log_file": str(svc.log_file),
            "options": {
                "sample_rates": SAMPLE_RATES,
                "bit_depths": [{"value": k, "label": v["label"]} for k, v in BIT_DEPTHS.items()],
                "channels": [{"value": k, "label": v} for k, v in CHANNEL_OPTIONS.items()],
                "extensions": sorted(AUDIO_EXTENSIONS),
            },
        }

    @app.get("/api/dashboard")
    def dashboard():
        return {
            "library": svc.library.stats(),
            "conversions": svc.converter.summary(),
            "recent_conversions": svc.converter.list(limit=6),
            "recent_logs": svc.log.list(limit=8),
            "spotify": svc.spotify.status(),
            "worklist": svc.db.scalar("SELECT COUNT(*) FROM spotify_tracks WHERE in_worklist=1"),
            "ffmpeg": bool(svc.ff.available()["ffmpeg"]),
        }

    @app.get("/api/settings")
    def get_settings():
        return svc.settings()

    @app.put("/api/settings")
    def put_settings(values: dict = Body(...)):
        return svc.update_settings(values)

    # ---- filesystem browser (local only) ---------------------------------
    @app.get("/api/fs/list")
    def fs_list(path: str = "", files: bool = True):
        if not path:
            if os.name == "nt":
                drives = [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]
                return {"path": "", "parent": None, "dirs": [{"name": d, "path": d} for d in drives], "files": []}
            path = str(Path.home())
        p = Path(path).expanduser()
        if not p.is_dir():
            raise HTTPException(404, "La carpeta no existe")
        dirs, fls = [], []
        try:
            for e in sorted(p.iterdir(), key=lambda x: x.name.lower()):
                if e.name.startswith("."):
                    continue
                try:
                    if e.is_dir():
                        dirs.append({"name": e.name, "path": str(e)})
                    elif files and e.suffix.lower() in AUDIO_EXTENSIONS:
                        fls.append({"name": e.name, "path": str(e), "size": e.stat().st_size})
                except OSError:
                    continue
        except PermissionError:
            raise HTTPException(403, "Sin permiso para leer esta carpeta")
        parent = str(p.parent) if p.parent != p else ("" if os.name == "nt" else None)
        return {"path": str(p), "parent": parent, "dirs": dirs, "files": fls}

    # ---- library ----------------------------------------------------------
    @app.post("/api/import")
    def start_import(req: ImportRequest):
        skip = svc.settings()["skip_exact_duplicates"] if req.skip_duplicates is None else req.skip_duplicates
        return svc.library.start_import(req.paths, req.recursive, skip).to_dict()

    @app.get("/api/import")
    def list_imports():
        return [j.to_dict() for j in reversed(list(svc.library.jobs.values()))]

    @app.get("/api/import/{job_id}")
    def get_import(job_id: str):
        job = svc.library.jobs.get(job_id)
        if not job:
            raise HTTPException(404, "Importación no encontrada")
        return job.to_dict()

    @app.post("/api/import/{job_id}/cancel")
    def cancel_import(job_id: str):
        return {"ok": svc.library.cancel_import(job_id)}

    @app.get("/api/library")
    def library(q: str = "", artist: str = "", album: str = "", genre: str = "", sort: str = "artist",
                limit: int = Query(500, le=5000), offset: int = 0):
        return svc.library.list(q, artist, album, genre, sort, limit, offset)

    @app.get("/api/library/facets")
    def facets():
        return svc.library.facets()

    @app.get("/api/library/duplicates")
    def duplicates():
        return svc.library.duplicates()

    @app.get("/api/library/{track_id}")
    def get_track(track_id: int):
        t = svc.library.get(track_id)
        if not t:
            raise HTTPException(404, "Pista no encontrada")
        return t

    @app.put("/api/library/{track_id}")
    def edit_track(track_id: int, req: MetadataRequest):
        try:
            return svc.library.update_metadata(track_id, req.values, req.write_to_file)
        except KeyError:
            raise HTTPException(404, "Pista no encontrada")
        except (OSError, RuntimeError) as e:
            raise HTTPException(422, f"No se pudieron escribir las etiquetas: {e}")

    @app.post("/api/library/remove")
    def remove_tracks(req: IdsRequest):
        return {"removed": svc.library.remove([int(i) for i in req.ids])}

    @app.get("/api/library/{track_id}/stream")
    def stream_track(track_id: int):
        t = svc.library.get(track_id)
        if not t or not os.path.isfile(t["path"]):
            raise HTTPException(404, "Archivo no disponible")
        return FileResponse(t["path"], media_type=_mime(t["path"]))

    @app.get("/api/library/{track_id}/candidates")
    def track_candidates(track_id: int):
        t = svc.library.get(track_id)
        if not t:
            raise HTTPException(404, "Pista no encontrada")
        from .services.matcher import score
        items = svc.spotify.worklist()
        return sorted(({**s, "score": score(t, s)} for s in items), key=lambda s: -s["score"])[:8]

    @app.put("/api/library/{track_id}/spotify")
    def link_spotify(track_id: int, body: dict = Body(...)):
        sid = body.get("spotify_id") or None
        if sid and body.get("track"):
            svc.spotify.add_to_worklist([body["track"]])
        if sid and not svc.db.query_one("SELECT id FROM spotify_tracks WHERE id=?", (sid,)):
            raise HTTPException(404, "Canción de Spotify desconocida; añádela antes a la lista de trabajo")
        svc.library.set_spotify_link(track_id, sid, 1.0 if sid else None)
        svc.log.info("match", "Asociación manual" if sid else "Asociación eliminada", {"track": track_id, "spotify": sid})
        return svc.library.get(track_id)

    # ---- spotify ------------------------------------------------------------
    @app.get("/api/spotify/status")
    def sp_status():
        return svc.spotify.status()

    @app.get("/api/spotify/login")
    def sp_login():
        return {"url": svc.spotify.authorize_url()}

    @app.get("/api/spotify/callback", response_class=HTMLResponse)
    def sp_callback(code: str | None = None, state: str | None = None, error: str | None = None):
        try:
            res = svc.spotify.handle_callback(code, state, error)
            name = (res.get("user") or {}).get("name") or "tu cuenta"
            return _callback_page(True, f"Conectado como {name}. Ya puedes cerrar esta ventana.")
        except SpotifyError as e:
            svc.log.error("spotify", "Fallo al conectar con Spotify", str(e))
            return _callback_page(False, str(e))

    @app.post("/api/spotify/logout")
    def sp_logout():
        svc.spotify.logout()
        return {"ok": True}

    @app.get("/api/spotify/search")
    def sp_search(q: str, type: str = "track", offset: int = 0, limit: int = 10):
        if type not in ("track", "album", "artist"):
            raise HTTPException(400, "Tipo de búsqueda no válido")
        return svc.spotify.search(q, type, limit, offset)

    @app.get("/api/spotify/playlists")
    def sp_playlists(offset: int = 0):
        return svc.spotify.playlists(offset=offset)

    @app.get("/api/spotify/playlists/{pid}")
    def sp_playlist(pid: str):
        return svc.spotify.playlist_tracks(pid)

    @app.get("/api/spotify/saved")
    def sp_saved():
        return svc.spotify.saved_tracks()

    @app.get("/api/spotify/albums/{aid}")
    def sp_album(aid: str):
        return svc.spotify.album_tracks(aid)

    @app.get("/api/spotify/artists/{aid}")
    def sp_artist(aid: str):
        return svc.spotify.artist_albums(aid)

    @app.get("/api/worklist")
    def wl():
        return svc.spotify.worklist()

    @app.post("/api/worklist")
    def wl_add(tracks: list[dict] = Body(...)):
        return {"added": svc.spotify.add_to_worklist(tracks)}

    @app.post("/api/worklist/remove")
    def wl_remove(req: IdsRequest):
        return {"removed": svc.spotify.remove_from_worklist([str(i) for i in req.ids])}

    @app.post("/api/worklist/match")
    def wl_match():
        return svc.matcher.auto_match()

    @app.get("/api/worklist/{sid}/candidates")
    def wl_candidates(sid: str):
        return svc.matcher.candidates_for_spotify(sid)

    # ---- conversions --------------------------------------------------------
    @app.post("/api/conversions")
    def convert(req: ConvertRequest):
        if not req.track_ids:
            raise HTTPException(400, "Selecciona al menos una pista")
        tracks = []
        for tid in req.track_ids:
            t = svc.library.get(tid)
            if not t:
                raise HTTPException(404, f"Pista {tid} no encontrada")
            if not os.path.isfile(t["path"]):
                raise HTTPException(422, f"El archivo de origen ya no existe: {t['path']}")
            tracks.append(t)
        spec = WavSpec(req.sample_rate, req.bit_depth, req.channels)
        return svc.converter.enqueue(tracks, spec, req.output_dir, req.naming_pattern)

    @app.get("/api/conversions")
    def conversions(status: str | None = None, batch_id: str | None = None, limit: int = 300, offset: int = 0):
        return svc.converter.list(status, batch_id, limit, offset)

    @app.get("/api/conversions/{cid}")
    def conversion(cid: int):
        j = svc.converter.get(cid)
        if not j:
            raise HTTPException(404, "Conversión no encontrada")
        return j

    @app.post("/api/conversions/{cid}/cancel")
    def cancel_conversion(cid: int):
        return {"ok": svc.converter.cancel(cid)}

    @app.post("/api/conversions/cancel-all")
    def cancel_all():
        return {"cancelled": svc.converter.cancel_all()}

    @app.post("/api/conversions/{cid}/retry")
    def retry_conversion(cid: int):
        new_id = svc.converter.retry(cid)
        if not new_id:
            raise HTTPException(400, "Solo se pueden reintentar conversiones fallidas o canceladas")
        return {"job_id": new_id}

    @app.post("/api/conversions/{cid}/verify")
    def verify_conversion(cid: int):
        j = svc.converter.get(cid)
        if not j or j["status"] != "done":
            raise HTTPException(400, "La conversión no está terminada")
        spec = WavSpec(j["sample_rate"], j["bit_depth"], j["channels"])
        src_dur = None
        try:
            src_dur = svc.ff.probe(j["source_path"])["duration"]
        except AudioError:
            pass
        report = svc.ff.verify_wav(j["output_path"], spec, src_dur)
        svc.db.execute("UPDATE conversions SET verified=?, verify_report=? WHERE id=?",
                       (1 if report["ok"] else 0, json.dumps(report), cid))
        svc.log.info("convert", f"Verificación manual #{cid}: {'OK' if report['ok'] else 'FALLO'}")
        return report

    @app.get("/api/conversions/{cid}/stream")
    def stream_conversion(cid: int):
        j = svc.converter.get(cid)
        if not j or not j["output_exists"]:
            raise HTTPException(404, "Archivo no disponible")
        return FileResponse(j["output_path"], media_type="audio/wav")

    @app.delete("/api/conversions")
    def clear_conversions():
        return {"removed": svc.converter.clear_history()}

    @app.post("/api/export")
    def export(req: ExportRequest):
        return svc.exporter.export(req.conversion_ids, req.dest_dir, req.naming_pattern, req.overwrite)

    # ---- logs ---------------------------------------------------------------
    @app.get("/api/logs")
    def logs(level: str | None = None, category: str | None = None, limit: int = 200, offset: int = 0):
        return svc.log.list(level, category, limit, offset)

    @app.delete("/api/logs")
    def clear_logs():
        svc.log.clear()
        return {"ok": True}

    # ---- frontend -------------------------------------------------------------
    if FRONTEND_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

    return app


def _hostname(host_header: str) -> str:
    if host_header.startswith("["):  # IPv6 literal
        return host_header.split("]")[0] + "]"
    return host_header.rsplit(":", 1)[0]


def _mime(path: str) -> str:
    return {".mp3": "audio/mpeg", ".flac": "audio/flac", ".m4a": "audio/mp4", ".aac": "audio/aac",
            ".ogg": "audio/ogg", ".oga": "audio/ogg", ".wav": "audio/wav"}.get(Path(path).suffix.lower(),
                                                                                "application/octet-stream")


def _callback_page(ok: bool, message: str) -> str:
    color = "#1ed760" if ok else "#ff5c7a"
    title = "Spotify conectado" if ok else "No se pudo conectar"
    import html
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><title>{title}</title>
<style>body{{background:#0d0f14;color:#e8eaf0;font-family:system-ui,sans-serif;display:grid;place-items:center;
height:100vh;margin:0}}.c{{text-align:center;max-width:420px}}h1{{color:{color};font-weight:600}}</style></head>
<body><div class="c"><h1>{title}</h1><p>{html.escape(message)}</p></div>
<script>try{{window.opener&&window.opener.postMessage({{type:'swc-spotify',ok:{str(ok).lower()}}},'*')}}catch(e){{}}
{"setTimeout(()=>window.close(),2500)" if ok else ""}</script></body></html>"""
