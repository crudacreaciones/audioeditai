"""Common contract for every audio source.

A provider only reports what its *real* API exposes. Nothing is downloadable unless the provider
explicitly states that its official mechanism allows the download (and under which licence).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

import httpx


class Availability(str, Enum):
    DOWNLOADABLE = "downloadable"              # Descargable
    PURCHASE_REQUIRED = "purchase_required"    # Requiere compra o autorización adicional
    STREAM_ONLY = "stream_only"                # Solo disponible para reproducción
    LICENSE_INCOMPATIBLE = "license_incompatible"  # Licencia incompatible
    UNAVAILABLE = "unavailable"                # No disponible
    UNVERIFIED_MATCH = "unverified_match"      # Coincidencia no verificada


class ProviderError(Exception):
    """Error talking to a provider. `transient` errors may be retried."""

    def __init__(self, message: str, transient: bool = False):
        super().__init__(message)
        self.transient = transient


@dataclass
class TrackQuery:
    title: str
    artists: list[str]
    album: str = ""
    duration: float | None = None  # seconds
    isrc: str = ""

    @property
    def main_artist(self) -> str:
        return self.artists[0] if self.artists else ""


@dataclass
class Capabilities:
    search: bool = True
    metadata: bool = True
    license_info: bool = True
    download: bool = False
    isrc: bool = False
    formats: list[str] = field(default_factory=list)
    requires_credentials: bool = False


@dataclass
class LicenseInfo:
    name: str
    url: str = ""
    allows_download: bool = False
    allows_conversion: bool = False
    requires_attribution: bool = False
    notes: str = ""


@dataclass
class Candidate:
    provider: str
    id: str
    title: str
    artist: str
    album: str = ""
    duration: float | None = None
    isrc: str = ""
    format: str = ""           # as declared by the provider ("flac", "mp3"…)
    bitrate_kbps: int | None = None
    lossless: bool = False
    page_url: str = ""
    license: LicenseInfo | None = None
    availability: Availability = Availability.UNAVAILABLE
    availability_reason: str = ""
    # filled by the matcher
    match_score: float = 0.0
    match_details: dict[str, Any] = field(default_factory=dict)
    # provider-private data needed to build the download (never sent to clients)
    _private: dict[str, Any] = field(default_factory=dict, repr=False)

    def public(self) -> dict:
        d = asdict(self)
        d.pop("_private", None)
        d["availability"] = self.availability.value
        return d


@dataclass
class DownloadInfo:
    url: str
    allowed_hosts: tuple[str, ...]   # the URL (and every redirect) must stay on these domains
    ext: str = ""
    size: int | None = None
    md5: str = ""


class AudioProvider(ABC):
    """Adapter for one audio source. Subclasses must only use the source's official API."""

    id: str = ""
    name: str = ""
    priority: int = 100  # lower = preferred when two candidates are otherwise equal

    def __init__(self, http: httpx.AsyncClient, settings):
        self.http = http
        self.settings = settings

    def configured(self) -> bool:
        """True when all credentials needed by the API are present."""
        return True

    def missing_configuration(self) -> list[str]:
        return []

    @abstractmethod
    def get_capabilities(self) -> Capabilities: ...

    @abstractmethod
    async def search(self, query: TrackQuery) -> list[Candidate]: ...

    async def get_metadata(self, candidate_id: str) -> Candidate | None:
        return None

    async def check_availability(self, candidate: Candidate) -> Availability:
        return candidate.availability

    async def check_license(self, candidate: Candidate) -> LicenseInfo | None:
        return candidate.license

    async def get_download(self, candidate: Candidate) -> DownloadInfo | None:
        return None

    @abstractmethod
    async def health_check(self) -> None:
        """Make a cheap real request; raise ProviderError when the API is not usable."""

    # helpers ---------------------------------------------------------------
    async def _get_json(self, url: str, params: dict | None = None) -> Any:
        try:
            r = await self.http.get(url, params=params)
        except (httpx.TimeoutException, httpx.TransportError) as e:
            raise ProviderError(f"{self.name}: sin conexión ({type(e).__name__})", transient=True) from e
        if r.status_code == 429 or r.status_code >= 500:
            raise ProviderError(f"{self.name}: HTTP {r.status_code}", transient=True)
        if r.status_code >= 400:
            raise ProviderError(f"{self.name}: HTTP {r.status_code}")
        try:
            return r.json()
        except ValueError as e:
            raise ProviderError(f"{self.name}: respuesta no válida") from e
