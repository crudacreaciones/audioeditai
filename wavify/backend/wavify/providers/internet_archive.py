"""Internet Archive (archive.org) adapter.

Official, key-less APIs:
  * Advanced Search  GET /advancedsearch.php?q=…&fl[]=…&rows=…&output=json
  * Metadata         GET /metadata/{identifier}
  * Download         GET /download/{identifier}/{file}
Only items that declare a Creative Commons / public-domain `licenseurl` and are not access-restricted are downloadable.
"""
from __future__ import annotations

import asyncio
import re
from urllib.parse import quote

from . import licenses
from .base import (AudioProvider, Availability, Candidate, Capabilities, DownloadInfo, LicenseInfo, ProviderError,
                   TrackQuery)

# IA "format" field -> (codec, lossless, nominal bitrate)
_FORMATS = {
    "flac": ("flac", True, None), "24bit flac": ("flac", True, None), "wave": ("wav", True, None),
    "aiff": ("aiff", True, None), "apple lossless audio": ("alac", True, None),
    "vbr mp3": ("mp3", False, None), "320kbps mp3": ("mp3", False, 320), "256kbps mp3": ("mp3", False, 256),
    "192kbps mp3": ("mp3", False, 192), "160kbps mp3": ("mp3", False, 160), "128kbps mp3": ("mp3", False, 128),
    "64kbps mp3": ("mp3", False, 64), "ogg vorbis": ("ogg", False, None),
}
_RANK = {"flac": 0, "wav": 0, "aiff": 0, "alac": 0, "mp3": 2, "ogg": 3}


def _esc(s: str) -> str:
    return re.sub(r'["\\]', " ", s).strip()


def _length(v) -> float | None:
    if v in (None, ""):
        return None
    s = str(v)
    try:
        if ":" in s:
            secs = 0.0
            for part in s.split(":"):
                secs = secs * 60 + float(part)
            return secs
        return float(s)
    except ValueError:
        return None


def _first(v) -> str:
    if isinstance(v, list):
        return str(v[0]) if v else ""
    return str(v or "")


class InternetArchiveProvider(AudioProvider):
    id = "internet_archive"
    name = "Internet Archive"
    priority = 20
    max_items = 6

    @property
    def base(self) -> str:
        return self.settings.internet_archive_url.rstrip("/")

    def get_capabilities(self) -> Capabilities:
        return Capabilities(search=True, metadata=True, license_info=True, download=True, isrc=False,
                            formats=["flac", "wav", "mp3", "ogg"], requires_credentials=False)

    async def health_check(self) -> None:
        data = await self._get_json(f"{self.base}/advancedsearch.php",
                                    {"q": "mediatype:(audio)", "fl[]": "identifier", "rows": 1, "output": "json"})
        if "response" not in data:
            raise ProviderError("Internet Archive: respuesta inesperada de advancedsearch")

    async def search(self, query: TrackQuery) -> list[Candidate]:
        title, artist = _esc(query.title), _esc(query.main_artist)
        if not title:
            return []
        q = f'mediatype:(audio) AND (title:("{title}") OR description:("{title}"))'
        if artist:
            q += f' AND creator:("{artist}")'
        data = await self._get_json(f"{self.base}/advancedsearch.php", {
            "q": q, "fl[]": ["identifier", "title", "creator", "licenseurl"], "rows": self.max_items, "output": "json"})
        docs = (data.get("response") or {}).get("docs") or []
        sem = asyncio.Semaphore(3)

        async def item(doc):
            async with sem:
                try:
                    return await self._item_candidates(doc["identifier"])
                except ProviderError:
                    return []

        groups = await asyncio.gather(*(item(d) for d in docs if d.get("identifier")))
        return [c for g in groups for c in g]

    async def get_metadata(self, candidate_id: str) -> Candidate | None:
        identifier, _, fname = candidate_id.partition("/")
        for c in await self._item_candidates(identifier):
            if c.id == candidate_id or not fname:
                return c
        return None

    async def _item_candidates(self, identifier: str) -> list[Candidate]:
        data = await self._get_json(f"{self.base}/metadata/{quote(identifier)}")
        meta = data.get("metadata") or {}
        files = data.get("files") or []
        lic = licenses.from_url(_first(meta.get("licenseurl")))
        restricted = str(meta.get("access-restricted-item", "")).lower() == "true"
        item_artist = _first(meta.get("creator"))
        item_album = _first(meta.get("title"))

        # group audio files by track (title or file stem) and keep the best-quality file of each track
        tracks: dict[str, dict] = {}
        for f in files:
            fmt = str(f.get("format", "")).lower()
            if fmt not in _FORMATS:
                continue
            codec, lossless, br = _FORMATS[fmt]
            stem = re.sub(r"\.[^.]+$", "", f.get("name", ""))
            key = (f.get("title") or stem).strip().lower()
            length = _length(f.get("length"))
            if br is None and not lossless and length and f.get("size"):
                try:
                    br = int(int(f["size"]) * 8 / length / 1000)
                except (ValueError, ZeroDivisionError):
                    br = None
            entry = {"file": f, "codec": codec, "lossless": lossless, "bitrate": br, "length": length}
            cur = tracks.get(key)
            if cur is None or (_RANK[codec], -(br or 0)) < (_RANK[cur["codec"]], -(cur["bitrate"] or 0)):
                tracks[key] = entry

        out = []
        for key, e in tracks.items():
            f = e["file"]
            if restricted:
                avail, reason = Availability.UNAVAILABLE, "Ítem con acceso restringido (préstamo)."
            elif lic.allows_download:
                avail, reason = Availability.DOWNLOADABLE, ""
            else:
                avail, reason = Availability.LICENSE_INCOMPATIBLE, lic.notes
            out.append(Candidate(
                provider=self.id, id=f"{identifier}/{f['name']}",
                title=f.get("title") or re.sub(r"\.[^.]+$", "", f["name"]),
                artist=f.get("artist") or f.get("creator") or item_artist,
                album=f.get("album") or item_album,
                duration=e["length"], format=e["codec"], bitrate_kbps=e["bitrate"], lossless=e["lossless"],
                page_url=f"https://archive.org/details/{identifier}", license=lic,
                availability=avail, availability_reason=reason,
                _private={"identifier": identifier, "name": f["name"], "size": f.get("size"), "md5": f.get("md5", "")},
            ))
        return out

    async def check_license(self, candidate: Candidate) -> LicenseInfo | None:
        return candidate.license

    async def get_download(self, candidate: Candidate) -> DownloadInfo | None:
        if candidate.availability != Availability.DOWNLOADABLE or not (candidate.license and candidate.license.allows_download):
            return None
        p = candidate._private
        size = int(p["size"]) if str(p.get("size") or "").isdigit() else None
        return DownloadInfo(url=f"{self.base}/download/{quote(p['identifier'])}/{quote(p['name'])}",
                            allowed_hosts=("archive.org",) + _extra_hosts(self.base),
                            ext=p["name"].rsplit(".", 1)[-1].lower(), size=size, md5=p.get("md5", ""))


def _extra_hosts(base: str) -> tuple[str, ...]:
    host = re.sub(r"^https?://", "", base).split("/")[0].split(":")[0]
    return () if host.endswith("archive.org") else (host,)
