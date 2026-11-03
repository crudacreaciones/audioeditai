"""Spotify Web API client (Authorization Code + PKCE). Metadata only: no audio is ever fetched."""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from ..db import Database, now
from ..oplog import OpLog

SCOPES = "playlist-read-private playlist-read-collaborative user-library-read"
TOKEN_KEY = "spotify_token"


class SpotifyError(Exception):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


class NotConnected(SpotifyError):
    pass


def simplify_track(t: dict, album: dict | None = None) -> dict | None:
    if not t or t.get("type", "track") != "track" or not t.get("id"):
        return None
    album = t.get("album") or album or {}
    images = album.get("images") or []
    return {
        "id": t["id"],
        "name": t.get("name", ""),
        "artists": ", ".join(a.get("name", "") for a in t.get("artists") or []),
        "artist_ids": [a.get("id") for a in t.get("artists") or []],
        "album": album.get("name", ""),
        "album_id": album.get("id"),
        "image_url": images[0]["url"] if images else "",
        "thumb_url": images[-1]["url"] if images else "",
        "duration_ms": int(t.get("duration_ms") or 0),
        "uri": t.get("uri", ""),
        "external_url": (t.get("external_urls") or {}).get("spotify", ""),
        "isrc": (t.get("external_ids") or {}).get("isrc", ""),
        "explicit": bool(t.get("explicit")),
    }


def simplify_album(a: dict) -> dict:
    images = a.get("images") or []
    return {
        "id": a.get("id"), "name": a.get("name", ""),
        "artists": ", ".join(x.get("name", "") for x in a.get("artists") or []),
        "image_url": images[0]["url"] if images else "",
        "release_date": a.get("release_date", ""), "total_tracks": a.get("total_tracks", 0),
        "external_url": (a.get("external_urls") or {}).get("spotify", ""),
    }


def simplify_artist(a: dict) -> dict:
    images = a.get("images") or []
    return {
        "id": a.get("id"), "name": a.get("name", ""),
        "genres": a.get("genres") or [],
        "image_url": images[0]["url"] if images else "",
        "external_url": (a.get("external_urls") or {}).get("spotify", ""),
    }


def simplify_playlist(p: dict) -> dict:
    images = p.get("images") or []
    tracks = p.get("items") or p.get("tracks") or {}
    return {
        "id": p.get("id"), "name": p.get("name", ""),
        "owner": (p.get("owner") or {}).get("display_name") or (p.get("owner") or {}).get("id", ""),
        "image_url": images[0]["url"] if images else "",
        "total": tracks.get("total", 0) if isinstance(tracks, dict) else 0,
        "external_url": (p.get("external_urls") or {}).get("spotify", ""),
    }


class SpotifyClient:
    def __init__(self, db: Database, log: OpLog, accounts_url: str, api_url: str, get_settings):
        self.db, self.log = db, log
        self.accounts_url, self.api_url = accounts_url, api_url
        self.get_settings = get_settings
        self._pending: dict[str, dict] = {}
        self._lock = threading.Lock()

    # ---- config ---------------------------------------------------------
    @property
    def client_id(self) -> str:
        return (self.get_settings().get("spotify_client_id") or "").strip()

    @property
    def redirect_uri(self) -> str:
        return self.get_settings()["spotify_redirect_uri"]

    def status(self) -> dict:
        tok = self.db.get_setting(TOKEN_KEY)
        return {
            "configured": bool(self.client_id),
            "connected": bool(tok and tok.get("refresh_token")),
            "user": (tok or {}).get("user"),
            "redirect_uri": self.redirect_uri,
            "scopes": SCOPES,
        }

    # ---- OAuth (PKCE) ---------------------------------------------------
    def authorize_url(self) -> str:
        if not self.client_id:
            raise SpotifyError("Configura el Client ID de tu app de Spotify en Configuración", 400)
        verifier = secrets.token_urlsafe(64)[:96]
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        state = secrets.token_urlsafe(16)
        with self._lock:
            # expire stale attempts
            for k in [k for k, v in self._pending.items() if v["ts"] < time.time() - 900]:
                self._pending.pop(k, None)
            self._pending[state] = {"verifier": verifier, "ts": time.time()}
        params = {
            "client_id": self.client_id, "response_type": "code", "redirect_uri": self.redirect_uri,
            "code_challenge_method": "S256", "code_challenge": challenge, "state": state, "scope": SCOPES,
        }
        return f"{self.accounts_url}/authorize?{urllib.parse.urlencode(params)}"

    def handle_callback(self, code: str | None, state: str | None, error: str | None = None) -> dict:
        if error:
            raise SpotifyError(f"Spotify rechazó la autorización: {error}")
        with self._lock:
            pending = self._pending.pop(state or "", None)
        if not pending or not code:
            raise SpotifyError("Respuesta de autorización no válida o caducada. Vuelve a intentarlo.")
        tok = self._token_request({
            "grant_type": "authorization_code", "code": code, "redirect_uri": self.redirect_uri,
            "client_id": self.client_id, "code_verifier": pending["verifier"],
        })
        self._save_token(tok)
        try:
            me = self.api("GET", "/me")
            user = {"id": me.get("id"), "name": me.get("display_name") or me.get("id"),
                    "image": ((me.get("images") or [{}])[0] or {}).get("url", ""),
                    "product": me.get("product", "")}
        except SpotifyError:
            user = None
        stored = self.db.get_setting(TOKEN_KEY)
        stored["user"] = user
        self.db.set_setting(TOKEN_KEY, stored)
        self.log.info("spotify", f"Cuenta de Spotify conectada: {(user or {}).get('name', '?')}")
        return {"user": user}

    def logout(self) -> None:
        self.db.delete_setting(TOKEN_KEY)
        self.log.info("spotify", "Cuenta de Spotify desconectada")

    def _save_token(self, tok: dict) -> None:
        old = self.db.get_setting(TOKEN_KEY) or {}
        self.db.set_setting(TOKEN_KEY, {
            "access_token": tok["access_token"],
            "refresh_token": tok.get("refresh_token") or old.get("refresh_token"),
            "expires_at": now() + int(tok.get("expires_in", 3600)) - 60,
            "scope": tok.get("scope", ""),
            "user": old.get("user"),
        })

    def _token_request(self, data: dict) -> dict:
        req = urllib.request.Request(
            f"{self.accounts_url}/api/token", data=urllib.parse.urlencode(data).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            raise SpotifyError(f"Error de autenticación con Spotify ({e.code}): {body[:200]}", e.code) from e
        except urllib.error.URLError as e:
            raise SpotifyError(f"No se pudo contactar con Spotify: {e.reason}") from e

    def _access_token(self) -> str:
        tok = self.db.get_setting(TOKEN_KEY)
        if not tok or not tok.get("refresh_token"):
            raise NotConnected("Conecta tu cuenta de Spotify primero", 401)
        if tok.get("expires_at", 0) <= now():
            self._refresh()
            tok = self.db.get_setting(TOKEN_KEY)
        return tok["access_token"]

    def _refresh(self) -> None:
        tok = self.db.get_setting(TOKEN_KEY) or {}
        try:
            new = self._token_request({"grant_type": "refresh_token", "refresh_token": tok.get("refresh_token", ""),
                                       "client_id": self.client_id})
        except SpotifyError as e:
            if e.status in (400, 401):
                self.logout()
                raise NotConnected("La sesión de Spotify ha caducado. Vuelve a conectar tu cuenta.", 401) from e
            raise
        self._save_token(new)

    # ---- Web API --------------------------------------------------------
    def api(self, method: str, path: str, params: dict | None = None, _retry: int = 0):
        url = path if path.startswith("http") else f"{self.api_url}{path}"
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        req = urllib.request.Request(url, method=method, headers={
            "Authorization": f"Bearer {self._access_token()}", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                raw = r.read()
                return json.loads(raw.decode()) if raw else {}
        except urllib.error.HTTPError as e:
            if e.code == 401 and _retry < 1:
                self._refresh()
                return self.api(method, path, params, _retry + 1)
            if e.code == 429 and _retry < 3:
                wait = min(int(e.headers.get("Retry-After") or 1), 10)
                time.sleep(wait)
                return self.api(method, path, params, _retry + 1)
            try:
                msg = json.loads(e.read().decode()).get("error", {}).get("message", "")
            except (ValueError, AttributeError):
                msg = ""
            raise SpotifyError(f"Spotify API {e.code}: {msg or e.reason}", e.code) from e
        except urllib.error.URLError as e:
            raise SpotifyError(f"No se pudo contactar con Spotify: {e.reason}") from e

    def search(self, q: str, types: str = "track", limit: int = 10, offset: int = 0) -> dict:
        if not q.strip():
            return {"tracks": [], "albums": [], "artists": [], "total": 0}
        data = self.api("GET", "/search", {"q": q, "type": types, "limit": max(1, min(int(limit), 10)), "offset": offset})
        tracks = data.get("tracks") or {}
        return {
            "tracks": [x for x in (simplify_track(t) for t in tracks.get("items") or []) if x],
            "albums": [simplify_album(a) for a in (data.get("albums") or {}).get("items") or [] if a],
            "artists": [simplify_artist(a) for a in (data.get("artists") or {}).get("items") or [] if a],
            "total": max((data.get(k) or {}).get("total", 0) for k in ("tracks", "albums", "artists")),
        }

    def playlists(self, limit: int = 50, offset: int = 0) -> dict:
        data = self.api("GET", "/me/playlists", {"limit": limit, "offset": offset})
        return {"items": [simplify_playlist(p) for p in data.get("items") or [] if p], "total": data.get("total", 0)}

    def _paged_tracks(self, first_path: str, params: dict, max_items: int = 500) -> list[dict]:
        out: list[dict] = []
        data = self.api("GET", first_path, params)
        while True:
            for entry in data.get("items") or []:
                # playlist/saved-track pages wrap the track ("item" in newer API versions, "track" in older)
                if isinstance(entry, dict) and ("item" in entry or "track" in entry):
                    t = entry.get("item") or entry.get("track")
                else:
                    t = entry
                s = simplify_track(t)
                if s:
                    out.append(s)
            if not data.get("next") or len(out) >= max_items:
                return out
            data = self.api("GET", data["next"])

    def playlist_tracks(self, playlist_id: str) -> list[dict]:
        try:
            return self._paged_tracks(f"/playlists/{playlist_id}/items", {"limit": 50})
        except SpotifyError as e:
            if e.status != 404:
                raise
            return self._paged_tracks(f"/playlists/{playlist_id}/tracks", {"limit": 50})

    def saved_tracks(self) -> list[dict]:
        return self._paged_tracks("/me/tracks", {"limit": 50}, max_items=200)

    def album_tracks(self, album_id: str) -> dict:
        album = self.api("GET", f"/albums/{album_id}")
        tracks = []
        page = album.get("tracks") or {}
        while True:
            tracks += [x for x in (simplify_track(t, album) for t in page.get("items") or []) if x]
            if not page.get("next"):
                break
            page = self.api("GET", page["next"])
        return {"album": simplify_album(album), "tracks": tracks}

    def artist_albums(self, artist_id: str) -> dict:
        artist = self.api("GET", f"/artists/{artist_id}")
        albums = self.api("GET", f"/artists/{artist_id}/albums", {"include_groups": "album,single", "limit": 10})
        return {"artist": simplify_artist(artist),
                "albums": [simplify_album(a) for a in albums.get("items") or [] if a]}

    # ---- work list (local) ----------------------------------------------
    def worklist(self) -> list[dict]:
        rows = self.db.query(
            "SELECT s.*, (SELECT t.id FROM tracks t WHERE t.spotify_id=s.id LIMIT 1) AS local_track_id "
            "FROM spotify_tracks s WHERE in_worklist=1 ORDER BY added_at DESC")
        return rows

    def add_to_worklist(self, tracks: list[dict]) -> int:
        n = 0
        for t in tracks:
            if not t.get("id") or not t.get("name"):
                continue
            self.db.execute(
                "INSERT INTO spotify_tracks(id, name, artists, album, image_url, duration_ms, uri, external_url, isrc, "
                "in_worklist, added_at) VALUES (?,?,?,?,?,?,?,?,?,1,?) ON CONFLICT(id) DO UPDATE SET in_worklist=1, "
                "name=excluded.name, artists=excluded.artists, album=excluded.album, image_url=excluded.image_url, "
                "duration_ms=excluded.duration_ms",
                (t["id"], t["name"], t.get("artists", ""), t.get("album", ""), t.get("image_url", ""),
                 int(t.get("duration_ms") or 0), t.get("uri", ""), t.get("external_url", ""), t.get("isrc", ""), now()))
            n += 1
        if n:
            self.log.info("spotify", f"{n} canciones añadidas a la lista de trabajo")
        return n

    def remove_from_worklist(self, ids: list[str]) -> int:
        if not ids:
            return 0
        qs = ",".join("?" for _ in ids)
        return self.db.execute(f"UPDATE spotify_tracks SET in_worklist=0 WHERE id IN ({qs})", ids).rowcount
