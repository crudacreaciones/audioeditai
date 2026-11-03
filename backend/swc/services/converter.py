"""Conversion job queue: persistent jobs, worker threads, progress, cancellation, verification."""
from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import threading
import uuid
from pathlib import Path

from ..db import Database, now
from ..oplog import OpLog
from .audio import AudioError, ConversionCancelled, FFmpeg, WavSpec, sha256_file

ACTIVE = ("queued", "running")
_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_filename(name: str, max_len: int = 150) -> str:
    name = _INVALID.sub("_", name).strip().strip(".")
    name = re.sub(r"\s+", " ", name)
    return (name or "audio")[:max_len]


def render_name(pattern: str, track: dict) -> str:
    fields = {k: (str(track.get(k) or "").strip()) for k in
              ("artist", "title", "album", "album_artist", "genre", "year", "track_no")}
    if not fields["title"]:
        fields["title"] = Path(track.get("path") or track.get("source_path") or "audio").stem
    if not fields["artist"]:
        fields["artist"] = "Desconocido"
    try:
        name = (pattern or "{artist} - {title}").format(**fields)
    except (KeyError, ValueError, IndexError):
        name = "{artist} - {title}".format(**fields)
    return safe_filename(name)


def unique_path(path: Path, reserved: set[str] | None = None) -> Path:
    reserved = reserved or set()
    candidate, i = path, 1
    while candidate.exists() or str(candidate) in reserved:
        candidate = path.with_name(f"{path.stem} ({i}){path.suffix}")
        i += 1
    return candidate


class ConversionManager:
    def __init__(self, db: Database, ffmpeg: FFmpeg, log: OpLog, get_settings):
        self.db, self.ff, self.log = db, ffmpeg, log
        self.get_settings = get_settings
        self._queue: "queue.Queue[int | None]" = queue.Queue()
        self._cancel: dict[int, threading.Event] = {}
        self._procs: dict[int, subprocess.Popen] = {}
        self._progress: dict[int, float] = {}
        self._lock = threading.Lock()
        self._reserved: set[str] = set()
        self._workers: list[threading.Thread] = []
        self._stopping = False

    # ---- lifecycle ------------------------------------------------------
    def start(self, workers: int | None = None) -> None:
        # Jobs that were running when the app closed cannot be resumed safely.
        n = self.db.execute("UPDATE conversions SET status='failed', error='Interrumpido al cerrar la aplicación', "
                            "finished_at=? WHERE status='running'", (now(),)).rowcount
        if n:
            self.log.warning("convert", f"{n} conversiones interrumpidas en la sesión anterior")
        workers = max(1, min(8, int(workers or self.get_settings().get("concurrency", 2))))
        for _ in range(workers):
            t = threading.Thread(target=self._worker, daemon=True)
            t.start()
            self._workers.append(t)
        for row in self.db.query("SELECT id FROM conversions WHERE status='queued' ORDER BY id"):
            self._cancel[row["id"]] = threading.Event()
            self._queue.put(row["id"])

    def stop(self) -> None:
        self._stopping = True
        for jid in list(self._cancel):
            self._cancel[jid].set()
        for p in list(self._procs.values()):
            try:
                p.kill()
            except OSError:
                pass
        for _ in self._workers:
            self._queue.put(None)

    # ---- API ------------------------------------------------------------
    def enqueue(self, tracks: list[dict], spec: WavSpec, output_dir: str | None = None,
                naming_pattern: str | None = None) -> dict:
        spec.validate()
        settings = self.get_settings()
        out_dir = Path(output_dir or settings["output_dir"]).expanduser()
        out_dir.mkdir(parents=True, exist_ok=True)
        pattern = naming_pattern or settings.get("naming_pattern") or "{artist} - {title}"
        batch_id = uuid.uuid4().hex[:10]
        ids = []
        for t in tracks:
            with self._lock:
                target = unique_path(out_dir / (render_name(pattern, t) + ".wav"), self._reserved)
                self._reserved.add(str(target))
            cur = self.db.execute(
                "INSERT INTO conversions(batch_id, track_id, source_path, output_path, sample_rate, bit_depth, "
                "channels, status, created_at) VALUES (?,?,?,?,?,?,?, 'queued', ?)",
                (batch_id, t.get("id"), t["path"], str(target), spec.sample_rate, spec.bit_depth, spec.channels, now()))
            jid = cur.lastrowid
            self._cancel[jid] = threading.Event()
            ids.append(jid)
        for jid in ids:
            self._queue.put(jid)
        self.log.info("convert", f"Lote {batch_id}: {len(ids)} conversiones en cola",
                      {"sample_rate": spec.sample_rate, "bit_depth": spec.bit_depth, "channels": spec.channels,
                       "output_dir": str(out_dir)})
        return {"batch_id": batch_id, "job_ids": ids}

    def cancel(self, job_id: int) -> bool:
        job = self.get(job_id)
        if not job or job["status"] not in ACTIVE:
            return False
        ev = self._cancel.setdefault(job_id, threading.Event())
        ev.set()
        proc = self._procs.get(job_id)
        if proc and proc.poll() is None:
            try:
                proc.kill()
            except OSError:
                pass
        if job["status"] == "queued":
            self._finish(job_id, "cancelled", error="Cancelado por el usuario")
        return True

    def cancel_all(self) -> int:
        return sum(1 for j in self.db.query("SELECT id FROM conversions WHERE status IN ('queued','running')")
                   if self.cancel(j["id"]))

    def retry(self, job_id: int) -> int | None:
        job = self.get(job_id)
        if not job or job["status"] not in ("failed", "cancelled"):
            return None
        track = {"id": job["track_id"], "path": job["source_path"],
                 "title": Path(job["output_path"]).stem, "artist": ""}
        spec = WavSpec(job["sample_rate"], job["bit_depth"], job["channels"])
        out_dir = str(Path(job["output_path"]).parent)
        return self.enqueue([track], spec, out_dir, "{title}")["job_ids"][0]

    def get(self, job_id: int) -> dict | None:
        job = self.db.query_one("SELECT * FROM conversions WHERE id=?", (job_id,))
        if job:
            self._decorate(job)
        return job

    def list(self, status: str | None = None, batch_id: str | None = None, limit: int = 300, offset: int = 0) -> list[dict]:
        sql = ("SELECT c.*, t.title, t.artist, t.album FROM conversions c LEFT JOIN tracks t ON t.id=c.track_id "
               "WHERE 1=1")
        params: list = []
        if status == "active":
            sql += " AND c.status IN ('queued','running')"
        elif status:
            sql += " AND c.status=?"
            params.append(status)
        if batch_id:
            sql += " AND c.batch_id=?"
            params.append(batch_id)
        sql += " ORDER BY c.id DESC LIMIT ? OFFSET ?"
        params += [limit, offset]
        jobs = self.db.query(sql, params)
        for j in jobs:
            self._decorate(j)
        return jobs

    def summary(self) -> dict:
        rows = self.db.query("SELECT status, COUNT(*) n FROM conversions GROUP BY status")
        out = {r["status"]: r["n"] for r in rows}
        out["output_bytes"] = self.db.scalar("SELECT COALESCE(SUM(output_size),0) FROM conversions WHERE status='done'")
        return out

    def clear_history(self) -> int:
        return self.db.execute("DELETE FROM conversions WHERE status NOT IN ('queued','running')").rowcount

    def _decorate(self, job: dict) -> None:
        if job["status"] == "running" and job["id"] in self._progress:
            job["progress"] = self._progress[job["id"]]
        try:
            job["verify_report"] = json.loads(job["verify_report"]) if job["verify_report"] else None
        except (TypeError, ValueError):
            pass
        job["output_exists"] = bool(job["output_path"]) and os.path.isfile(job["output_path"])

    # ---- worker ---------------------------------------------------------
    def _finish(self, job_id: int, status: str, **fields) -> None:
        fields.update(status=status, finished_at=now())
        if status == "done":
            fields["progress"] = 1.0
        sets = ", ".join(f"{k}=?" for k in fields)
        self.db.execute(f"UPDATE conversions SET {sets} WHERE id=?", list(fields.values()) + [job_id])
        self._progress.pop(job_id, None)

    def _worker(self) -> None:
        while True:
            job_id = self._queue.get()
            if job_id is None or self._stopping:
                return
            try:
                self._run(job_id)
            except Exception as e:  # never let a worker die
                self._finish(job_id, "failed", error=f"Error interno: {e!r}")
                self.log.error("convert", f"Error interno en conversión #{job_id}", repr(e))
            finally:
                self._procs.pop(job_id, None)
                self._cancel.pop(job_id, None)

    def _run(self, job_id: int) -> None:
        job = self.db.query_one("SELECT * FROM conversions WHERE id=?", (job_id,))
        if not job or job["status"] != "queued":
            return
        cancel = self._cancel.setdefault(job_id, threading.Event())
        if cancel.is_set():
            self._finish(job_id, "cancelled", error="Cancelado por el usuario")
            return
        claimed = self.db.execute("UPDATE conversions SET status='running', started_at=?, progress=0 "
                                  "WHERE id=? AND status='queued'", (now(), job_id)).rowcount
        if not claimed:  # cancelled meanwhile
            return
        spec = WavSpec(job["sample_rate"], job["bit_depth"], job["channels"])
        src, dst = job["source_path"], job["output_path"]
        name = os.path.basename(src)
        last_saved = [0.0]

        def on_progress(p: float) -> None:
            self._progress[job_id] = p
            if p - last_saved[0] >= 0.1:
                last_saved[0] = p
                self.db.execute("UPDATE conversions SET progress=? WHERE id=?", (p, job_id))

        try:
            src_info = self.ff.probe(src)
            self.ff.convert(src, dst, spec, duration=src_info["duration"], on_progress=on_progress,
                            cancel_event=cancel, register_process=lambda p: self._procs.__setitem__(job_id, p))
            report = None
            verified = 0
            if self.get_settings().get("verify_after_convert", True):
                report = self.ff.verify_wav(dst, spec, src_info["duration"])
                verified = 1 if report["ok"] else 0
                if not report["ok"]:
                    bad = [c for c in report["checks"] if not c["ok"]]
                    raise AudioError("La verificación de integridad falló: " +
                                     "; ".join(f"{c['name']}: {c['detail']}" for c in bad))
            self._finish(job_id, "done", verified=verified, verify_report=json.dumps(report) if report else "",
                         output_hash=sha256_file(dst), output_size=os.path.getsize(dst), error="")
            self.log.info("convert", f"Convertido: {name} → {os.path.basename(dst)}",
                          {"id": job_id, "verificado": bool(verified)})
        except ConversionCancelled:
            self._finish(job_id, "cancelled", error="Cancelado por el usuario")
            self.log.info("convert", f"Conversión cancelada: {name}", {"id": job_id})
        except AudioError as e:
            if os.path.exists(dst) and not self.db.scalar("SELECT verified FROM conversions WHERE id=?", (job_id,)):
                # do not leave an unverified/corrupt output behind
                try:
                    os.remove(dst)
                except OSError:
                    pass
            self._finish(job_id, "failed", error=str(e))
            self.log.error("convert", f"Conversión fallida: {name}", {"id": job_id, "error": str(e)})
        finally:
            with self._lock:
                self._reserved.discard(dst)
