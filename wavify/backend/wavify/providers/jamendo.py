"""Jamendo adapter (API v3.0, https://developer.jamendo.com/v3.0).

Requires a free client id (JAMENDO_CLIENT_ID). Each track declares `audiodownload_allowed` and its Creative Commons
licence (`license_ccurl`); the download URL is `audiodownload`. Tracks whose artist disabled downloads are "stream only".
"""
from __future__ import annotations

import re

from . import licenses
from .base import (AudioProvider, Availability, Candidate, Capabilities, DownloadInfo, LicenseInfo, ProviderError,
                   TrackQuery)


class JamendoProvider(AudioProvider):
    id = "jamendo"
    name = "Jamendo"
    priority = 10

    @property
    def base(self) -> str:
        return self.settings.jamendo_api_url.rstrip("/")

    def configured(self) -> bool:
        return bool(self.settings.jamendo_client_id)

    def missing_configuration(self) -> list[str]:
        return [] if self.configured() else ["JAMENDO_CLIENT_ID"]

    def get_capabilities(self) -> Capabilities:
        return Capabilities(search=True, metadata=True, license_info=True, download=True, isrc=False,
                            formats=["mp3", "flac"], requires_credentials=True)

    def _params(self, **extra) -> dict:
        return {"client_id": self.settings.jamendo_client_id, "format": "json", **extra}

    async def _call(self, path: str, **params) -> list[dict]:
        if not self.configured():
            raise ProviderError("Jamendo: falta JAMENDO_CLIENT_ID")
        data = await self._get_json(f"{self.base}/{path}/", self._params(**params))
        headers = data.get("headers") or {}
        if headers.get("status") != "success":
            raise ProviderError(f"Jamendo: {headers.get('error_message') or 'error de la API'} (código {headers.get('code')})")
        return data.get("results") or []

    async def health_check(self) -> None:
        await self._call("tracks", limit=1)

    async def search(self, query: TrackQuery) -> list[Candidate]:
        terms = " ".join(x for x in (query.main_artist, query.title) if x).strip()
        if not terms:
            return []
        results = await self._call("tracks", search=terms, limit=10, include="licenses",
                                   audioformat="mp32", audiodlformat="flac")
        return [self._candidate(t) for t in results if t.get("id")]

    async def get_metadata(self, candidate_id: str) -> Candidate | None:
        results = await self._call("tracks", id=candidate_id, include="licenses", audiodlformat="flac")
        return self._candidate(results[0]) if results else None

    def _candidate(self, t: dict) -> Candidate:
        lic = licenses.from_url(t.get("license_ccurl"))
        allowed = t.get("audiodownload_allowed")
        dl = t.get("audiodownload") or ""
        if allowed is False:
            avail, reason = Availability.STREAM_ONLY, "El artista no permite la descarga en Jamendo."
        elif not dl:
            avail, reason = Availability.STREAM_ONLY, "Jamendo no ofrece archivo de descarga para esta pista."
        elif not lic.allows_download:
            avail, reason = Availability.LICENSE_INCOMPATIBLE, lic.notes
        else:
            avail, reason = Availability.DOWNLOADABLE, ""
        fmt = "flac" if re.search(r"flac", dl, re.I) else "mp3"
        return Candidate(
            provider=self.id, id=str(t["id"]), title=t.get("name", ""), artist=t.get("artist_name", ""),
            album=t.get("album_name", ""), duration=float(t["duration"]) if t.get("duration") else None,
            format=fmt, lossless=fmt == "flac", page_url=t.get("shareurl", ""), license=lic,
            availability=avail, availability_reason=reason, _private={"download": dl},
        )

    async def check_license(self, candidate: Candidate) -> LicenseInfo | None:
        return candidate.license

    async def get_download(self, candidate: Candidate) -> DownloadInfo | None:
        url = candidate._private.get("download")
        if candidate.availability != Availability.DOWNLOADABLE or not url:
            return None
        if not url.startswith("https://"):
            url = re.sub(r"^http://", "https://", url)
        return DownloadInfo(url=url, allowed_hosts=("jamendo.com",) + _test_hosts(self.base), ext=candidate.format)


def _test_hosts(base: str) -> tuple[str, ...]:
    host = re.sub(r"^https?://", "", base).split("/")[0].split(":")[0]
    return () if host.endswith("jamendo.com") else (host,)
