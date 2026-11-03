"""HTTP API used by the WAVIFY mobile app."""
from __future__ import annotations

import hmac
import logging
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from .config import MP3_BITRATES, Settings
from .jobs import JobManager
from .providers.registry import ProviderRegistry
from .search import SearchCoordinator
from .spotify import LinkError, SpotifyClient, parse_link

VERSION = "1.0.0"
log = logging.getLogger("wavify")


class JobRequest(BaseModel):
    url: str = Field(..., max_length=500)
    bitrate: int = 320


class RateLimiter:
    """Sliding window per client IP."""

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self.hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        q = self.hits[key]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= self.per_minute:
            return False
        q.append(now)
        return True


def create_app(settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None,
               check_providers_on_start: bool = True) -> FastAPI:
    settings = settings or Settings.from_env()
    state: dict = {}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        http = httpx.AsyncClient(timeout=httpx.Timeout(20, connect=10), transport=transport,
                                 headers={"User-Agent": f"WAVIFY/{VERSION} (+https://github.com/crudacreaciones/audioeditai)"})
        registry = ProviderRegistry(settings, http)
        registry.load_from_settings()
        spotify = SpotifyClient(http, settings)
        search = SearchCoordinator(registry, settings)
        jobs = JobManager(settings, http, spotify, search, registry)
        jobs.start()
        state.update(http=http, registry=registry, spotify=spotify, search=search, jobs=jobs,
                     limiter=RateLimiter(settings.jobs_per_minute))
        app.state.wavify = state
        if check_providers_on_start:
            await registry.check_all()
        yield
        await jobs.stop()
        await http.aclose()

    app = FastAPI(title="WAVIFY API", version=VERSION, lifespan=lifespan)
    if settings.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_methods=["GET", "POST"],
                           allow_headers=["Content-Type"])

    def admin(token: str | None) -> None:
        if not settings.admin_token or not token or not hmac.compare_digest(token, settings.admin_token):
            raise HTTPException(403, "No autorizado")

    @app.get("/api/v1/health")
    async def health():
        reg = state["registry"]
        return {"ok": True, "version": VERSION, "spotify_configured": state["spotify"].configured(),
                "active_providers": len(reg.active())}

    @app.get("/api/v1/providers")
    async def providers():
        return state["registry"].summary()

    @app.post("/api/v1/providers/check")
    async def providers_check(x_admin_token: str | None = Header(None)):
        admin(x_admin_token)
        return await state["registry"].check_all()

    @app.post("/api/v1/providers/{pid}/{action}")
    async def provider_toggle(pid: str, action: str, x_admin_token: str | None = Header(None)):
        admin(x_admin_token)
        if action not in ("enable", "disable"):
            raise HTTPException(404, "Acción no válida")
        if not state["registry"].set_enabled(pid, action == "enable"):
            raise HTTPException(404, "Proveedor no encontrado")
        state["search"].clear_cache()
        return state["registry"].get(pid).to_dict()

    @app.post("/api/v1/jobs", status_code=202)
    async def create_job(req: JobRequest, request: Request):
        if req.bitrate not in MP3_BITRATES:
            raise HTTPException(422, f"Calidad no válida. Opciones: {', '.join(map(str, MP3_BITRATES))} kbps")
        try:
            parse_link(req.url)  # reject garbage before creating a job
        except LinkError as e:
            raise HTTPException(422, str(e))
        ip = request.client.host if request.client else "?"
        if not state["limiter"].allow(ip):
            return JSONResponse({"detail": "Demasiadas peticiones. Espera un minuto."}, status_code=429,
                                headers={"Retry-After": "60"})
        job = state["jobs"].create(req.url, req.bitrate)
        return job.public()

    @app.get("/api/v1/jobs/{job_id}")
    async def get_job(job_id: str, details: bool = False):
        job = state["jobs"].get(job_id)
        if not job:
            raise HTTPException(404, "Trabajo no encontrado o caducado")
        return job.public(include_candidates=details)

    @app.post("/api/v1/jobs/{job_id}/cancel")
    async def cancel_job(job_id: str):
        if not state["jobs"].get(job_id):
            raise HTTPException(404, "Trabajo no encontrado")
        return {"cancelled": state["jobs"].cancel(job_id)}

    @app.get("/api/v1/jobs/{job_id}/file")
    async def get_file(job_id: str, token: str = ""):
        job = state["jobs"].get(job_id)
        if not job or not token or not hmac.compare_digest(token, job.token):
            raise HTTPException(404, "Archivo no encontrado")
        if job.stage != "ready" or not job.file_path or not job.file_path.exists():
            raise HTTPException(410, "El archivo ya no está disponible. Vuelve a convertir la canción.")
        return FileResponse(job.file_path, media_type="audio/mpeg", filename=job.file["name"],
                            headers={"Cache-Control": "no-store"})

    return app
