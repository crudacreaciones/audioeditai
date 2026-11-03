"""Spotify link parsing + Web API (Client Credentials flow). Metadata only — Spotify never provides audio files here."""
from __future__ import annotations

import asyncio
import base64
import re
import time
from dataclasses import asdict, dataclass, field
from urllib.parse import urlparse

import httpx

_ID = r"[A-Za-z0-9]{22}"
_URI = re.compile(rf"^spotify:(track|album|playlist|artist|episode|show):({_ID})$")
_PATH = re.compile(rf"^/(?:intl-[a-z]{{2}}(?:-[a-z]{{2}})?/)?(?:embed/)?(track|album|playlist|artist|episode|show)/({_ID})/?$", re.I)
SHORT_HOSTS = {"spotify.link", "spoti.fi"}
WEB_HOSTS = {"open.spotify.com", "play.spotify.com"}


class LinkError(ValueError):
    """The text is not a usable Spotify track link (message is user-facing)."""


class SpotifyError(Exception):
    def __init__(self, message: str, code: str = "spotify_error", retryable: bool = True):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass
class SpotifyLink:
    kind: str
    id: str = ""
    short_url: str = ""

    @property
    def needs_resolution(self) -> bool:
        return bool(self.short_url)


@dataclass
class TrackInfo:
    id: str
    title: str
    artists: list[str]
    album: str
    cover_url: str
    duration: float  # seconds
    isrc: str
    url: str
    release_date: str = ""
    explicit: bool = False
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("extra", None)
        return d


def parse_link(text: str) -> SpotifyLink:
    text = (text or "").strip()
    if not text:
        raise LinkError("Pega un enlace de Spotify.")
    if len(text) > 500:
        raise LinkError("El enlace es demasiado largo.")
    m = _URI.match(text)
    if m:
        return _track_only(SpotifyLink(m.group(1), m.group(2)))
    if not re.match(r"^https?://", text, re.I):
        text = "https://" + text
    try:
        u = urlparse(text)
    except ValueError:
        raise LinkError("El enlace no es válido.")
    host = (u.hostname or "").lower()
    if host in SHORT_HOSTS:
        if not re.fullmatch(r"/[A-Za-z0-9_\-]{4,40}/?", u.path or ""):
            raise LinkError("El enlace corto de Spotify no es válido.")
        return SpotifyLink("short", short_url=f"https://{host}{u.path.rstrip('/')}")
    if host not in WEB_HOSTS:
        raise LinkError("Solo se admiten enlaces de Spotify (open.spotify.com).")
    m = _PATH.match(u.path or "")
    if not m:
        raise LinkError("No se reconoce el enlace de Spotify. Copia el enlace de una canción con «Compartir → Copiar enlace».")
    return _track_only(SpotifyLink(m.group(1).lower(), m.group(2)))


def _track_only(link: SpotifyLink) -> SpotifyLink:
    if link.kind != "track":
        names = {"album": "un álbum", "playlist": "una playlist", "artist": "un artista",
                 "episode": "un episodio de pódcast", "show": "un pódcast"}
        raise LinkError(f"Ese enlace es de {names.get(link.kind, 'otro tipo de contenido')}. Pega el enlace de una canción.")
    return link


class SpotifyClient:
    def __init__(self, http: httpx.AsyncClient, settings):
        self.http = http
        self.settings = settings
        self._token: str = ""
        self._token_exp: float = 0.0
        self._lock = asyncio.Lock()

    def configured(self) -> bool:
        return bool(self.settings.spotify_client_id and self.settings.spotify_client_secret)

    async def resolve_short_link(self, link: SpotifyLink) -> SpotifyLink:
        """Follow spotify.link / spoti.fi redirects (max 3) and accept only an open.spotify.com track URL."""
        url = link.short_url
        for _ in range(3):
            try:
                r = await self.http.get(url, follow_redirects=False)
            except httpx.HTTPError as e:
                raise SpotifyError("No se pudo abrir el enlace corto de Spotify.", "network") from e
            loc = r.headers.get("location")
            if r.status_code not in (301, 302, 303, 307, 308) or not loc:
                break
            host = (urlparse(loc).hostname or "").lower()
            if host in WEB_HOSTS:
                return parse_link(loc)
            if host not in SHORT_HOSTS:
                break
            url = loc
        raise LinkError("El enlace corto no lleva a una canción de Spotify.")

    async def _get_token(self) -> str:
        if not self.configured():
            raise SpotifyError("El servidor no tiene configuradas las credenciales de Spotify.", "spotify_not_configured",
                               retryable=False)
        async with self._lock:
            if self._token and self._token_exp > time.time():
                return self._token
            basic = base64.b64encode(f"{self.settings.spotify_client_id}:{self.settings.spotify_client_secret}".encode()).decode()
            try:
                r = await self.http.post(f"{self.settings.spotify_accounts_url.rstrip('/')}/api/token",
                                         data={"grant_type": "client_credentials"},
                                         headers={"Authorization": f"Basic {basic}"})
            except httpx.HTTPError as e:
                raise SpotifyError("No se pudo conectar con Spotify.", "network") from e
            if r.status_code in (400, 401):
                raise SpotifyError("Las credenciales de Spotify del servidor no son válidas.", "spotify_auth", retryable=False)
            if r.status_code != 200:
                raise SpotifyError(f"Spotify no está disponible (HTTP {r.status_code}).", "spotify_unavailable")
            data = r.json()
            self._token = data["access_token"]
            self._token_exp = time.time() + int(data.get("expires_in", 3600)) - 60
            return self._token

    async def get_track(self, track_id: str) -> TrackInfo:
        if not re.fullmatch(_ID, track_id or ""):
            raise LinkError("Identificador de canción no válido.")
        for attempt in range(3):
            token = await self._get_token()
            try:
                r = await self.http.get(f"{self.settings.spotify_api_url.rstrip('/')}/tracks/{track_id}",
                                        headers={"Authorization": f"Bearer {token}"})
            except httpx.HTTPError as e:
                raise SpotifyError("No se pudo conectar con Spotify.", "network") from e
            if r.status_code == 401 and attempt == 0:
                self._token = ""  # expired/revoked: get a new one
                continue
            if r.status_code == 429 and attempt < 2:
                await asyncio.sleep(min(float(r.headers.get("retry-after") or 1), 5))
                continue
            if r.status_code in (400, 404):
                raise SpotifyError("Spotify no encuentra esa canción.", "track_not_found", retryable=False)
            if r.status_code == 403:
                raise SpotifyError("Spotify ha denegado el acceso a esta canción para la app del servidor.",
                                   "spotify_forbidden", retryable=False)
            if r.status_code != 200:
                raise SpotifyError(f"Spotify no está disponible (HTTP {r.status_code}).", "spotify_unavailable")
            return self._to_track(r.json())
        raise SpotifyError("Spotify está limitando las peticiones. Inténtalo en unos segundos.", "rate_limited")

    @staticmethod
    def _to_track(d: dict) -> TrackInfo:
        album = d.get("album") or {}
        images = album.get("images") or []
        return TrackInfo(
            id=d["id"], title=d.get("name", ""),
            artists=[a.get("name", "") for a in d.get("artists") or [] if a.get("name")],
            album=album.get("name", ""), cover_url=images[0]["url"] if images else "",
            duration=(d.get("duration_ms") or 0) / 1000, isrc=(d.get("external_ids") or {}).get("isrc", "") or "",
            url=(d.get("external_urls") or {}).get("spotify", f"https://open.spotify.com/track/{d['id']}"),
            release_date=album.get("release_date", ""), explicit=bool(d.get("explicit")),
        )
