"""Authorized download engine.

Only DownloadInfo objects produced by a provider's `get_download` (i.e. after the licence/availability checks) reach
this module. The URL and every redirect must stay on the provider's declared domains, over HTTPS (plain HTTP is only
accepted for loopback hosts used by tests).
"""
from __future__ import annotations

import hashlib
import ipaddress
import os
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import httpx

from .providers.base import DownloadInfo


class DownloadError(Exception):
    pass


def _host_allowed(url: str, allowed: tuple[str, ...]) -> bool:
    u = urlparse(url)
    host = (u.hostname or "").lower()
    if not host:
        return False
    if u.scheme != "https":
        try:
            if not (u.scheme == "http" and ipaddress.ip_address(host).is_loopback):
                return False
        except ValueError:
            return False
    return any(host == a or host.endswith("." + a) for a in allowed)


async def download(http: httpx.AsyncClient, info: DownloadInfo, dest: Path, max_bytes: int,
                   on_progress: Callable[[float], None] | None = None) -> Path:
    if not _host_allowed(info.url, info.allowed_hosts):
        raise DownloadError("La URL de descarga no pertenece a la fuente autorizada.")
    if info.size and info.size > max_bytes:
        raise DownloadError("El archivo supera el tamaño máximo permitido.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    md5 = hashlib.md5()
    received = 0
    url = info.url
    try:
        for _ in range(6):  # manual redirects so every hop is validated
            async with http.stream("GET", url, follow_redirects=False) as r:
                if r.status_code in (301, 302, 303, 307, 308):
                    nxt = httpx.URL(url).join(r.headers.get("location", "")).__str__()
                    if not _host_allowed(nxt, info.allowed_hosts):
                        raise DownloadError("La fuente redirige a un dominio no autorizado.")
                    url = nxt
                    continue
                if r.status_code == 403 or r.status_code == 401:
                    raise DownloadError("La fuente ha denegado la descarga.")
                if r.status_code == 404:
                    raise DownloadError("El archivo ya no está disponible en la fuente.")
                if r.status_code != 200:
                    raise DownloadError(f"La fuente respondió con un error (HTTP {r.status_code}).")
                ctype = r.headers.get("content-type", "")
                if ctype.startswith(("text/html", "application/json")):
                    raise DownloadError("La fuente no devolvió un archivo de audio.")
                total = int(r.headers.get("content-length") or info.size or 0)
                if total > max_bytes:
                    raise DownloadError("El archivo supera el tamaño máximo permitido.")
                with open(tmp, "wb") as f:
                    async for chunk in r.aiter_bytes(1 << 16):
                        received += len(chunk)
                        if received > max_bytes:
                            raise DownloadError("El archivo supera el tamaño máximo permitido.")
                        md5.update(chunk)
                        f.write(chunk)
                        if on_progress and total:
                            on_progress(min(1.0, received / total))
                break
        else:
            raise DownloadError("Demasiadas redirecciones.")
        if received == 0:
            raise DownloadError("La fuente devolvió un archivo vacío.")
        if info.md5 and md5.hexdigest() != info.md5.lower():
            raise DownloadError("El archivo descargado está dañado (la suma MD5 no coincide).")
        os.replace(tmp, dest)
        return dest
    except httpx.HTTPError as e:
        raise DownloadError("Se interrumpió la descarga.") from e
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
