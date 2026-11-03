"""Export converted WAV files to a user-selected folder (copy + hash verification)."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from ..db import Database
from ..oplog import OpLog
from .audio import sha256_file
from .converter import render_name, unique_path


class Exporter:
    def __init__(self, db: Database, log: OpLog):
        self.db, self.log = db, log

    def export(self, conversion_ids: list[int], dest_dir: str, naming_pattern: str | None = None,
               overwrite: bool = False) -> dict:
        if not dest_dir:
            raise ValueError("Selecciona una carpeta de destino")
        dest = Path(dest_dir).expanduser()
        dest.mkdir(parents=True, exist_ok=True)
        results = {"exported": [], "errors": []}
        for cid in conversion_ids:
            job = self.db.query_one(
                "SELECT c.*, t.title, t.artist, t.album, t.album_artist, t.genre, t.year, t.track_no "
                "FROM conversions c LEFT JOIN tracks t ON t.id=c.track_id WHERE c.id=?", (cid,))
            if not job:
                results["errors"].append({"id": cid, "error": "Conversión no encontrada"})
                continue
            src = job["output_path"]
            if job["status"] != "done" or not os.path.isfile(src):
                results["errors"].append({"id": cid, "error": "El archivo WAV no está disponible"})
                continue
            if naming_pattern:
                name = render_name(naming_pattern, {**job, "path": src}) + ".wav"
            else:
                name = os.path.basename(src)
            target = dest / name
            if not overwrite:
                target = unique_path(target)
            try:
                tmp = str(target) + ".part"
                shutil.copyfile(src, tmp)
                expected = job["output_hash"] or sha256_file(src)
                if sha256_file(tmp) != expected:
                    os.remove(tmp)
                    raise OSError("La copia no coincide con el original (hash distinto)")
                os.replace(tmp, target)
                results["exported"].append({"id": cid, "path": str(target)})
            except OSError as e:
                results["errors"].append({"id": cid, "error": str(e)})
        self.log.info("export", f"Exportados {len(results['exported'])} WAV a {dest}",
                      {"errores": len(results["errors"])})
        return results
