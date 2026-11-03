"""The WAVIFY pipeline: link → Spotify metadata → parallel search → strict matching → licence checks →
authorized download → MP3 → ready. One job per request; temporary files are deleted after `file_ttl`."""
from __future__ import annotations

import asyncio
import logging
import secrets
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import converter
from .downloader import DownloadError, download
from .matching import match, quality_rank
from .providers.base import Availability, Candidate, ProviderError, TrackQuery
from .search import SearchCoordinator
from .spotify import LinkError, SpotifyClient, SpotifyError, parse_link

log = logging.getLogger("wavify.jobs")

# stage -> (start, end) of the overall progress bar
STAGES = {
    "analyzing": (0.00, 0.05), "identifying": (0.05, 0.15), "searching": (0.15, 0.40), "comparing": (0.40, 0.45),
    "checking": (0.45, 0.50), "downloading": (0.50, 0.80), "converting": (0.80, 0.99), "ready": (1.0, 1.0),
    "no_results": (1.0, 1.0), "error": (1.0, 1.0), "cancelled": (1.0, 1.0),
}
FINAL = {"ready", "no_results", "error", "cancelled"}
MESSAGES = {
    "analyzing": "Analizando enlace…", "identifying": "Identificando canción…", "searching": "Buscando en fuentes…",
    "comparing": "Comparando resultados…", "checking": "Comprobando permisos…", "downloading": "Descargando…",
    "converting": "Convirtiendo a MP3…", "ready": "Archivo listo", "cancelled": "Cancelado",
}
STATUS_LABELS = {
    Availability.DOWNLOADABLE: "Descargable", Availability.PURCHASE_REQUIRED: "Requiere compra o autorización",
    Availability.STREAM_ONLY: "Solo reproducción", Availability.LICENSE_INCOMPATIBLE: "Licencia incompatible",
    Availability.UNAVAILABLE: "No disponible", Availability.UNVERIFIED_MATCH: "Coincidencia no verificada",
}


@dataclass
class Job:
    url: str
    bitrate: int
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    token: str = field(default_factory=lambda: secrets.token_urlsafe(24))
    stage: str = "analyzing"
    stage_progress: float = 0.0
    message: str = MESSAGES["analyzing"]
    created: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)
    track: dict | None = None
    selected: dict | None = None
    summary: dict = field(default_factory=dict)
    candidates: list[dict] = field(default_factory=list)
    error: dict | None = None
    file: dict | None = None
    file_path: Path | None = None
    task: asyncio.Task | None = None

    @property
    def progress(self) -> float:
        a, b = STAGES[self.stage]
        return round(a + (b - a) * self.stage_progress, 3)

    def set_stage(self, stage: str, message: str | None = None) -> None:
        self.stage, self.stage_progress = stage, 0.0
        self.message = message or MESSAGES.get(stage, "")
        self.updated = time.time()

    def public(self, include_candidates: bool = False) -> dict:
        d = {"id": self.id, "stage": self.stage, "progress": self.progress, "message": self.message,
             "bitrate": self.bitrate, "track": self.track, "selected": self.selected, "summary": self.summary,
             "error": self.error, "file": self.file, "final": self.stage in FINAL, "updated": self.updated}
        if include_candidates:
            d["candidates"] = self.candidates
        return d


class JobManager:
    def __init__(self, settings, http, spotify: SpotifyClient, search: SearchCoordinator, registry):
        self.settings, self.http, self.spotify, self.search, self.registry = settings, http, spotify, search, registry
        self.jobs: dict[str, Job] = {}
        self._sem = asyncio.Semaphore(settings.max_concurrent_jobs)
        self._cleaner: asyncio.Task | None = None

    # ---- lifecycle ----------------------------------------------------------
    def start(self) -> None:
        self.settings.tmp_dir.mkdir(parents=True, exist_ok=True)
        # leftovers from a previous run are never served again
        for p in self.settings.tmp_dir.iterdir():
            shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
        self._cleaner = asyncio.create_task(self._cleanup_loop())

    async def stop(self) -> None:
        if self._cleaner:
            self._cleaner.cancel()
        for j in self.jobs.values():
            if j.task and not j.task.done():
                j.task.cancel()
        await asyncio.sleep(0)

    async def _cleanup_loop(self) -> None:
        while True:
            await asyncio.sleep(30)
            self.cleanup()

    def cleanup(self, now: float | None = None) -> int:
        now = now or time.time()
        removed = 0
        for jid, j in list(self.jobs.items()):
            if j.stage in FINAL and now - j.updated > self.settings.file_ttl:
                self._remove_files(j)
                self.jobs.pop(jid, None)
                removed += 1
        return removed

    def _job_dir(self, job: Job) -> Path:
        return self.settings.tmp_dir / job.id

    def _remove_files(self, job: Job) -> None:
        shutil.rmtree(self._job_dir(job), ignore_errors=True)
        job.file_path = None

    # ---- API ----------------------------------------------------------------
    def create(self, url: str, bitrate: int) -> Job:
        job = Job(url=url, bitrate=bitrate)
        self.jobs[job.id] = job
        job.task = asyncio.create_task(self._run(job))
        return job

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def cancel(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if not job or job.stage in FINAL:
            return False
        if job.task:
            job.task.cancel()
        return True

    # ---- pipeline -------------------------------------------------------------
    def _fail(self, job: Job, code: str, message: str, retryable: bool = True) -> None:
        job.set_stage("error", message)
        job.error = {"code": code, "message": message, "retryable": retryable}
        log.info("job=%s error code=%s msg=%s", job.id, code, message)

    def _no_results(self, job: Job, reason: str, message: str) -> None:
        job.set_stage("no_results", message)
        job.summary["reason"] = reason
        log.info("job=%s no_results reason=%s", job.id, reason)

    async def _run(self, job: Job) -> None:
        try:
            await self._pipeline(job)
        except asyncio.CancelledError:
            job.set_stage("cancelled")
            self._remove_files(job)
        except LinkError as e:
            self._fail(job, "invalid_link", str(e), retryable=False)
        except SpotifyError as e:
            self._fail(job, e.code, str(e), e.retryable)
        except (DownloadError, converter.ConversionError) as e:
            self._remove_files(job)
            self._fail(job, "download_failed" if isinstance(e, DownloadError) else "conversion_failed", str(e))
        except Exception as e:  # never leave a job hanging
            log.exception("job=%s unexpected error", job.id)
            self._remove_files(job)
            self._fail(job, "internal", "Ha ocurrido un error inesperado. Inténtalo de nuevo.")
            job.error["detail"] = type(e).__name__

    async def _pipeline(self, job: Job) -> None:
        # 1. analyse link
        link = parse_link(job.url)
        if link.needs_resolution:
            link = await self.spotify.resolve_short_link(link)

        # 2. identify
        job.set_stage("identifying")
        track = await self.spotify.get_track(link.id)
        job.track = track.to_dict()
        query = TrackQuery(title=track.title, artists=track.artists, album=track.album, duration=track.duration,
                           isrc=track.isrc)

        # 3. search every active provider in parallel
        job.set_stage("searching")
        if not self.registry.active():
            self._fail(job, "no_providers", "No hay fuentes de audio disponibles en este momento. Inténtalo más tarde.")
            return
        results = await self.search.search_all(query)
        job.summary["providers"] = [{"id": r.provider, "name": r.name, "ok": r.ok, "results": len(r.candidates)}
                                    for r in results]
        if results and all(not r.ok for r in results):
            self._fail(job, "providers_unavailable", "Las fuentes de audio no responden. Inténtalo de nuevo en unos minutos.")
            return

        # 4. compare
        job.set_stage("comparing")
        cands: list[Candidate] = [c for r in results for c in r.candidates]
        verified: list[Candidate] = []
        for c in cands:
            m = match(query, c)
            c.match_score, c.match_details = m.score, {**m.details, "reasons": m.reasons, "verified": m.verified}
            if m.verified:
                verified.append(c)
            else:
                c.availability, c.availability_reason = Availability.UNVERIFIED_MATCH, "; ".join(m.reasons)
        cands.sort(key=lambda c: c.match_score, reverse=True)

        # 5. permissions: licence + availability, from the provider itself
        job.set_stage("checking")
        downloadable: list[Candidate] = []
        for c in verified:
            prov = self.registry.get(c.provider).provider
            try:
                c.license = await prov.check_license(c)
                c.availability = await prov.check_availability(c)
            except ProviderError as e:
                c.availability, c.availability_reason = Availability.UNAVAILABLE, str(e)
            if c.availability == Availability.DOWNLOADABLE and c.license and c.license.allows_download \
                    and c.license.allows_conversion:
                downloadable.append(c)
            elif c.availability == Availability.DOWNLOADABLE:
                c.availability = Availability.LICENSE_INCOMPATIBLE
        job.candidates = [c.public() for c in cands[:15]]
        counts: dict[str, int] = {}
        for c in cands:
            counts[c.availability.value] = counts.get(c.availability.value, 0) + 1
        job.summary.update({"evaluated": len(cands), "verified": len(verified), "by_status": counts})

        if not downloadable:
            if not cands:
                self._no_results(job, "not_found", "No hemos encontrado esta canción en ninguna fuente de descarga autorizada.")
            elif not verified:
                self._no_results(job, "no_reliable_match",
                                 "Hemos encontrado resultados parecidos, pero ninguno es con seguridad la misma grabación. "
                                 "No se descarga nada para evitar un archivo incorrecto.")
            else:
                best = max(verified, key=lambda c: c.match_score)
                job.selected = self._selected(best)
                self._no_results(job, "not_downloadable",
                                 f"La canción está en {self._provider_name(best)}, pero no hay una versión descargable "
                                 f"autorizada ({STATUS_LABELS[best.availability].lower()}).")
            return

        # 6. pick the best: exact match first, then quality, then provider priority
        best = max(downloadable, key=lambda c: (round(c.match_score, 2), quality_rank(c),
                                                 -self.registry.get(c.provider).provider.priority))
        job.selected = self._selected(best)

        async with self._sem:
            # 7. authorized download
            job.set_stage("downloading")
            info = await self.registry.get(best.provider).provider.get_download(best)
            if info is None:
                raise DownloadError("La fuente no proporciona un enlace de descarga autorizado.")
            src = self._job_dir(job) / f"source.{info.ext or 'bin'}"
            await download(self.http, info, src, self.settings.max_download_bytes,
                           on_progress=lambda p: setattr(job, "stage_progress", p))

            # 8. convert
            job.set_stage("converting")
            lic = best.license
            artist = ", ".join(track.artists)
            tags = {"title": track.title, "artist": artist, "album": track.album, "date": track.release_date[:4],
                    "comment": f"WAVIFY · Fuente: {self._provider_name(best)} {best.page_url} · "
                               f"Licencia: {lic.name} {lic.url}".strip(),
                    "copyright": f"{lic.name} {lic.url}".strip()}
            name = converter.clean_filename(artist, track.title)
            out = self._job_dir(job) / "output.mp3"
            res = await converter.to_mp3(src, out, job.bitrate, tags,
                                         on_progress=lambda p: setattr(job, "stage_progress", p))
            src.unlink(missing_ok=True)

        job.file_path = out
        job.file = {"name": name, "size": res["size"], "bitrate_kbps": res["bitrate_kbps"], "note": res["note"],
                    "duration": res["duration"], "source_lossless": res["source_lossless"],
                    "download_path": f"/api/v1/jobs/{job.id}/file?token={job.token}",
                    "expires_at": time.time() + self.settings.file_ttl}
        job.set_stage("ready")
        log.info("job=%s ready provider=%s id=%s bitrate=%s", job.id, best.provider, best.id, res["bitrate_kbps"])

    def _provider_name(self, c: Candidate) -> str:
        st = self.registry.get(c.provider)
        return st.provider.name if st else c.provider

    def _selected(self, c: Candidate) -> dict:
        lic = c.license
        return {"provider": c.provider, "provider_name": self._provider_name(c), "title": c.title, "artist": c.artist,
                "album": c.album, "page_url": c.page_url, "availability": c.availability.value,
                "availability_label": STATUS_LABELS[c.availability], "match_score": c.match_score,
                "lossless": c.lossless, "license": None if not lic else {
                    "name": lic.name, "url": lic.url, "requires_attribution": lic.requires_attribution, "notes": lic.notes}}
