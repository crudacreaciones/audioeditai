"""Local music library: import (files/folders), duplicates, metadata, facets."""
from __future__ import annotations

import os
import re
import threading
import unicodedata
import uuid
from pathlib import Path

from ..config import AUDIO_EXTENSIONS
from ..db import Database, now
from ..oplog import OpLog
from .audio import AudioError, FFmpeg, sha256_file
from .metadata import EDITABLE_FIELDS, read_tags, write_tags


def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\((feat|ft|with)[^)]*\)|\[[^\]]*\]", " ", s)
    s = re.sub(r"\s-\s(remaster(ed)?|\d{4} remaster(ed)?|live|radio edit|mono|stereo)( version)?.*$", " ", s)
    s = re.sub(r"\((\d{4} )?remaster(ed)?[^)]*\)", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def iter_audio_files(paths: list[str], recursive: bool = True):
    for p in paths:
        p = os.path.expanduser(p)
        if os.path.isfile(p):
            if Path(p).suffix.lower() in AUDIO_EXTENSIONS:
                yield os.path.abspath(p)
        elif os.path.isdir(p):
            if recursive:
                for root, dirs, files in os.walk(p):
                    dirs[:] = sorted(d for d in dirs if not d.startswith("."))
                    for f in sorted(files):
                        if Path(f).suffix.lower() in AUDIO_EXTENSIONS and not f.startswith("."):
                            yield os.path.abspath(os.path.join(root, f))
            else:
                for f in sorted(os.listdir(p)):
                    fp = os.path.join(p, f)
                    if os.path.isfile(fp) and Path(f).suffix.lower() in AUDIO_EXTENSIONS:
                        yield os.path.abspath(fp)


class ImportJob:
    def __init__(self, paths: list[str], recursive: bool):
        self.id = uuid.uuid4().hex[:12]
        self.paths = paths
        self.recursive = recursive
        self.status = "scanning"
        self.total = 0
        self.processed = 0
        self.imported: list[dict] = []
        self.updated: list[dict] = []
        self.duplicates: list[dict] = []
        self.errors: list[dict] = []
        self.current = ""
        self.started_at = now()
        self.finished_at: float | None = None
        self.cancel_event = threading.Event()

    def to_dict(self) -> dict:
        return {
            "id": self.id, "paths": self.paths, "status": self.status, "total": self.total,
            "processed": self.processed, "current": self.current,
            "imported": self.imported, "updated": self.updated,
            "duplicates": self.duplicates, "errors": self.errors,
            "started_at": self.started_at, "finished_at": self.finished_at,
        }


class Library:
    def __init__(self, db: Database, ffmpeg: FFmpeg, log: OpLog):
        self.db, self.ff, self.log = db, ffmpeg, log
        self.jobs: dict[str, ImportJob] = {}
        self._lock = threading.Lock()

    # ---- import ---------------------------------------------------------
    def start_import(self, paths: list[str], recursive: bool = True, skip_duplicates: bool = True) -> ImportJob:
        paths = [p for p in (paths or []) if p and p.strip()]
        if not paths:
            raise ValueError("No se indicó ninguna ruta")
        job = ImportJob(paths, recursive)
        with self._lock:
            self.jobs[job.id] = job
            # keep the most recent 20 jobs in memory
            for old in list(self.jobs)[:-20]:
                self.jobs.pop(old, None)
        threading.Thread(target=self._run_import, args=(job, skip_duplicates), daemon=True).start()
        return job

    def import_now(self, paths: list[str], recursive: bool = True, skip_duplicates: bool = True) -> ImportJob:
        job = ImportJob(paths, recursive)
        self._run_import(job, skip_duplicates)
        return job

    def _run_import(self, job: ImportJob, skip_duplicates: bool) -> None:
        try:
            missing = [p for p in job.paths if not os.path.exists(os.path.expanduser(p))]
            for p in missing:
                job.errors.append({"path": p, "error": "La ruta no existe"})
            files = list(iter_audio_files(job.paths, job.recursive))
            job.total = len(files)
            job.status = "importing"
            self.log.info("import", f"Importación iniciada: {len(files)} archivos", {"paths": job.paths})
            for f in files:
                if job.cancel_event.is_set():
                    job.status = "cancelled"
                    break
                job.current = f
                try:
                    res = self.import_file(f, skip_duplicates)
                    getattr(job, res["result"]).append(res)
                except AudioError as e:
                    job.errors.append({"path": f, "error": str(e)})
                    self.log.warning("import", f"Archivo rechazado: {os.path.basename(f)}", {"path": f, "error": str(e)})
                except Exception as e:  # keep going on unexpected per-file failures
                    job.errors.append({"path": f, "error": f"{type(e).__name__}: {e}"})
                    self.log.error("import", f"Error importando {os.path.basename(f)}", {"path": f, "error": repr(e)})
                job.processed += 1
            if job.status != "cancelled":
                job.status = "done"
            self.log.info("import", "Importación finalizada", {
                "importados": len(job.imported), "actualizados": len(job.updated),
                "duplicados": len(job.duplicates), "errores": len(job.errors)})
        except Exception as e:
            job.status = "failed"
            job.errors.append({"path": "", "error": str(e)})
            self.log.error("import", "La importación falló", repr(e))
        finally:
            job.current = ""
            job.finished_at = now()

    def import_file(self, path: str, skip_duplicates: bool = True) -> dict:
        path = os.path.abspath(path)
        info = self.ff.probe(path)
        file_hash = sha256_file(path)
        existing = self.db.query_one("SELECT id, path FROM tracks WHERE path=?", (path,))
        dup = self.db.query_one("SELECT id, path, title, artist FROM tracks WHERE file_hash=? AND path<>?", (file_hash, path))
        if dup and skip_duplicates and not existing:
            return {"result": "duplicates", "path": path, "duplicate_of": dup}
        tags = read_tags(path, info["tags"])
        row = {
            "path": path, "file_hash": file_hash, **tags,
            "duration": info["duration"], "format": Path(path).suffix.lower().lstrip("."),
            "codec": info["codec"], "sample_rate": info["sample_rate"], "channels": info["channels"],
            "bit_depth": info["bit_depth"], "bitrate": info["bitrate"], "size": os.path.getsize(path),
        }
        ts = now()
        if existing:
            sets = ", ".join(f"{k}=?" for k in row if k != "path")
            self.db.execute(f"UPDATE tracks SET {sets}, updated_at=? WHERE id=?",
                            [v for k, v in row.items() if k != "path"] + [ts, existing["id"]])
            return {"result": "updated", "path": path, "id": existing["id"], "title": row["title"]}
        cols = ", ".join(row) + ", added_at, updated_at"
        qs = ", ".join("?" for _ in row) + ", ?, ?"
        cur = self.db.execute(f"INSERT INTO tracks({cols}) VALUES ({qs})", list(row.values()) + [ts, ts])
        return {"result": "imported", "path": path, "id": cur.lastrowid, "title": row["title"], "artist": row["artist"]}

    def cancel_import(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if not job:
            return False
        job.cancel_event.set()
        return True

    # ---- queries --------------------------------------------------------
    def get(self, track_id: int) -> dict | None:
        return self.db.query_one(
            "SELECT t.*, s.name AS spotify_name, s.artists AS spotify_artists, s.image_url AS spotify_image, "
            "s.external_url AS spotify_url FROM tracks t LEFT JOIN spotify_tracks s ON s.id=t.spotify_id WHERE t.id=?",
            (track_id,))

    def list(self, q: str = "", artist: str = "", album: str = "", genre: str = "", sort: str = "artist",
             limit: int = 500, offset: int = 0) -> dict:
        where, params = ["1=1"], []
        if q:
            like = f"%{q}%"
            where.append("(t.title LIKE ? OR t.artist LIKE ? OR t.album LIKE ? OR t.genre LIKE ? OR t.path LIKE ?)")
            params += [like] * 5
        for col, val in (("artist", artist), ("album", album), ("genre", genre)):
            if val:
                where.append(f"t.{col}=?")
                params.append(val)
        order = {
            "artist": "t.artist COLLATE NOCASE, t.album COLLATE NOCASE, CAST(t.track_no AS INTEGER), t.title COLLATE NOCASE",
            "title": "t.title COLLATE NOCASE",
            "album": "t.album COLLATE NOCASE, CAST(t.track_no AS INTEGER)",
            "added": "t.added_at DESC",
            "duration": "t.duration DESC",
        }.get(sort, "t.artist COLLATE NOCASE")
        w = " AND ".join(where)
        total = self.db.scalar(f"SELECT COUNT(*) FROM tracks t WHERE {w}", params)
        items = self.db.query(
            f"SELECT t.*, s.name AS spotify_name, s.image_url AS spotify_image, s.external_url AS spotify_url, "
            f"(SELECT COUNT(*) FROM conversions c WHERE c.track_id=t.id AND c.status='done') AS wav_count "
            f"FROM tracks t LEFT JOIN spotify_tracks s ON s.id=t.spotify_id WHERE {w} ORDER BY {order} LIMIT ? OFFSET ?",
            params + [limit, offset])
        return {"total": total, "items": items}

    def facets(self) -> dict:
        out = {}
        for col in ("artist", "album", "genre"):
            out[col] = self.db.query(
                f"SELECT {col} AS value, COUNT(*) AS count FROM tracks WHERE {col}<>'' "
                f"GROUP BY {col} COLLATE NOCASE ORDER BY {col} COLLATE NOCASE")
        return out

    def duplicates(self) -> list[dict]:
        """Groups of exact duplicates (same hash) and probable duplicates (same normalized artist+title, ~same length)."""
        groups = []
        for row in self.db.query("SELECT file_hash, COUNT(*) n FROM tracks GROUP BY file_hash HAVING n>1"):
            items = self.db.query("SELECT * FROM tracks WHERE file_hash=? ORDER BY added_at", (row["file_hash"],))
            groups.append({"kind": "exact", "reason": "Contenido idéntico (SHA-256)", "items": items})
        buckets: dict[str, list[dict]] = {}
        for t in self.db.query("SELECT * FROM tracks"):
            key = normalize(t["artist"]) + "|" + normalize(t["title"])
            if key.strip("|"):
                buckets.setdefault(key, []).append(t)
        for key, items in buckets.items():
            if len(items) < 2:
                continue
            items.sort(key=lambda t: t["duration"])
            cluster = [items[0]]
            for t in items[1:]:
                if abs(t["duration"] - cluster[-1]["duration"]) <= 3:
                    cluster.append(t)
            # identical-content groups are already reported as "exact"
            if len(cluster) > 1 and len({t["file_hash"] for t in cluster}) > 1:
                groups.append({"kind": "probable", "reason": "Mismo artista y título, duración similar", "items": cluster})
        return groups

    def update_metadata(self, track_id: int, values: dict, write_to_file: bool = False) -> dict:
        track = self.get(track_id)
        if not track:
            raise KeyError(track_id)
        clean = {k: str(v).strip() for k, v in values.items() if k in EDITABLE_FIELDS and v is not None}
        if not clean:
            return track
        if write_to_file:
            write_tags(track["path"], clean)
            clean["file_hash"] = sha256_file(track["path"])
            clean["size"] = os.path.getsize(track["path"])
        sets = ", ".join(f"{k}=?" for k in clean)
        self.db.execute(f"UPDATE tracks SET {sets}, updated_at=? WHERE id=?", list(clean.values()) + [now(), track_id])
        self.log.info("library", f"Metadatos editados: {clean.get('title') or track['title']}",
                      {"id": track_id, "campos": list(clean), "archivo": write_to_file})
        return self.get(track_id)

    def remove(self, ids: list[int]) -> int:
        if not ids:
            return 0
        qs = ",".join("?" for _ in ids)
        cur = self.db.execute(f"DELETE FROM tracks WHERE id IN ({qs})", ids)
        self.log.info("library", f"{cur.rowcount} pistas quitadas de la biblioteca (los archivos no se borran)")
        return cur.rowcount

    def set_spotify_link(self, track_id: int, spotify_id: str | None, score: float | None = None) -> None:
        self.db.execute("UPDATE tracks SET spotify_id=?, match_score=?, updated_at=? WHERE id=?",
                        (spotify_id, score, now(), track_id))

    def stats(self) -> dict:
        r = self.db.query_one("SELECT COUNT(*) n, COALESCE(SUM(duration),0) dur, COALESCE(SUM(size),0) size, "
                              "COUNT(DISTINCT NULLIF(artist,'')) artists, COUNT(DISTINCT NULLIF(album,'')) albums, "
                              "SUM(CASE WHEN spotify_id IS NOT NULL THEN 1 ELSE 0 END) linked FROM tracks")
        formats = self.db.query("SELECT format, COUNT(*) n FROM tracks GROUP BY format ORDER BY n DESC")
        return {"tracks": r["n"], "duration": r["dur"], "size": r["size"], "artists": r["artists"],
                "albums": r["albums"], "linked": r["linked"] or 0, "formats": formats}
