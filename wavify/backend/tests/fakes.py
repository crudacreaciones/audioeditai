"""TEST-ONLY simulation of the external services (Spotify, Internet Archive, Jamendo) as an httpx transport.

Response shapes follow each service's public documentation. Never used outside tests.
"""
from __future__ import annotations

import hashlib
import json
from urllib.parse import parse_qs, unquote, urlparse

import httpx

SPOTIFY_ID = "4uLU6hMCjMI75M1A2tKUQC"
OTHER_ID = "0000000000000000000001"
STREAM_ONLY_ID = "0000000000000000000002"
COVER_ONLY_ID = "0000000000000000000003"


class FakeInternet:
    def __init__(self, audio: dict[str, bytes]):
        self.audio = dict(audio)  # tests may mutate it
        self.calls: list[str] = []
        self.down: set[str] = set()          # hosts answering 503
        self.spotify_credentials = ("cid", "secret")
        self.tokens: set[str] = set()
        self.n = 0
        self.spotify_tracks = {
            SPOTIFY_ID: self._sp_track(SPOTIFY_ID, "Luz de Mañana", ["Aurora Libre"], "Cielos Abiertos", 6000, "ESA012300001"),
            OTHER_ID: self._sp_track(OTHER_ID, "Hit Comercial", ["Megastar"], "Charts", 6000, "USX000000001"),
            STREAM_ONLY_ID: self._sp_track(STREAM_ONLY_ID, "Solo Escucha", ["Banda Cerrada"], "Privado", 6000, ""),
            COVER_ONLY_ID: self._sp_track(COVER_ONLY_ID, "Canción Famosa", ["Autor Original"], "Clásicos", 6000, ""),
        }
        # Internet Archive items: identifier -> metadata document
        self.ia_items = {
            "aurora-libre-cielos": {
                "metadata": {"identifier": "aurora-libre-cielos", "title": "Cielos Abiertos", "creator": "Aurora Libre",
                             "licenseurl": "http://creativecommons.org/licenses/by-sa/4.0/", "mediatype": "audio"},
                "files": [
                    self._ia_file("01 Luz de Manana.flac", "Flac", "Luz de Mañana", "Aurora Libre", "6.00", "flac6"),
                    self._ia_file("01 Luz de Manana.mp3", "VBR MP3", "Luz de Mañana", "Aurora Libre", "6.01", "mp3_128"),
                    {"name": "cover.jpg", "format": "JPEG", "size": "1000"},
                ],
            },
            "tributo-famosa": {  # a cover by another artist, with a valid licence
                "metadata": {"identifier": "tributo-famosa", "title": "Tributo", "creator": "Banda Tributo",
                             "licenseurl": "https://creativecommons.org/publicdomain/zero/1.0/"},
                "files": [self._ia_file("famosa.flac", "Flac", "Canción Famosa (Cover)", "Banda Tributo", "6.0", "flac6")],
            },
            "megastar-norights": {  # no licence declared
                "metadata": {"identifier": "megastar-norights", "title": "Charts", "creator": "Megastar"},
                "files": [self._ia_file("hit.mp3", "VBR MP3", "Hit Comercial", "Megastar", "6.0", "mp3_128")],
            },
        }
        self.jamendo_tracks = [
            {"id": "1501", "name": "Solo Escucha", "duration": 6, "artist_name": "Banda Cerrada", "album_name": "Privado",
             "audiodownload": "https://prod-1.storage.jamendo.com/download/track/1501/flac/",
             "audiodownload_allowed": False, "license_ccurl": "http://creativecommons.org/licenses/by-nc-nd/3.0/",
             "shareurl": "https://www.jamendo.com/track/1501"},
            {"id": "1502", "name": "Luz de Mañana (Live)", "duration": 7, "artist_name": "Aurora Libre",
             "album_name": "En Vivo", "audiodownload": "https://prod-1.storage.jamendo.com/download/track/1502/mp32/",
             "audiodownload_allowed": True, "license_ccurl": "http://creativecommons.org/licenses/by/3.0/",
             "shareurl": "https://www.jamendo.com/track/1502"},
            {"id": "1503", "name": "Canción Famosa", "duration": 6, "artist_name": "Banda Tributo",
             "album_name": "Versiones", "audiodownload": "https://prod-1.storage.jamendo.com/download/track/1503/mp32/",
             "audiodownload_allowed": True, "license_ccurl": "http://creativecommons.org/licenses/by/3.0/",
             "shareurl": "https://www.jamendo.com/track/1503"},
        ]

    # ---- builders ----
    def _sp_track(self, tid, name, artists, album, ms, isrc):
        return {"id": tid, "name": name, "duration_ms": ms, "explicit": False,
                "artists": [{"id": f"a{i}", "name": a} for i, a in enumerate(artists)],
                "album": {"name": album, "release_date": "2024-03-01",
                          "images": [{"url": f"https://i.scdn.co/image/{tid}", "width": 640, "height": 640}]},
                "external_ids": {"isrc": isrc} if isrc else {},
                "external_urls": {"spotify": f"https://open.spotify.com/track/{tid}"}}

    def _ia_file(self, name, fmt, title, artist, length, audio_key):
        data = self.audio[audio_key]
        return {"name": name, "format": fmt, "title": title, "artist": artist, "length": length,
                "size": str(len(data)), "md5": hashlib.md5(data).hexdigest(), "source": "original", "_audio": audio_key}

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    # ---- router ----
    def handle(self, req: httpx.Request) -> httpx.Response:
        host = req.url.host
        self.calls.append(f"{req.method} {host}{req.url.path}")
        if host in self.down:
            return httpx.Response(503, text="down")
        if host == "accounts.spotify.com":
            return self._sp_token(req)
        if host == "api.spotify.com":
            return self._sp_api(req)
        if host in ("spotify.link", "spoti.fi"):
            if req.url.path == "/abc123":
                return httpx.Response(302, headers={"location": f"https://open.spotify.com/track/{SPOTIFY_ID}?si=x"})
            if req.url.path == "/evil12":
                return httpx.Response(302, headers={"location": "https://evil.example.com/track/x"})
            return httpx.Response(404)
        if host == "archive.org" or host.endswith(".archive.org"):
            return self._ia(req)
        if host == "api.jamendo.com":
            return self._jamendo(req)
        if host.endswith("storage.jamendo.com"):
            tid = req.url.path.split("/")[3]
            return httpx.Response(200, content=self.audio["mp3_128"], headers={"content-type": "audio/mpeg"})
        if host == "evil.example.com":
            return httpx.Response(200, content=b"x")
        return httpx.Response(404)

    def _sp_token(self, req):
        import base64
        auth = req.headers.get("authorization", "")
        cid, _, secret = base64.b64decode(auth.removeprefix("Basic ")).decode().partition(":")
        if (cid, secret) != self.spotify_credentials:
            return httpx.Response(400, json={"error": "invalid_client"})
        self.n += 1
        tok = f"tok{self.n}"
        self.tokens.add(tok)
        return httpx.Response(200, json={"access_token": tok, "token_type": "Bearer", "expires_in": 3600})

    def _sp_api(self, req):
        if req.headers.get("authorization", "").removeprefix("Bearer ") not in self.tokens:
            return httpx.Response(401, json={"error": {"status": 401, "message": "Invalid access token"}})
        parts = req.url.path.split("/")
        if len(parts) == 4 and parts[2] == "tracks":
            t = self.spotify_tracks.get(parts[3])
            return httpx.Response(200, json=t) if t else httpx.Response(404, json={"error": {"status": 404}})
        return httpx.Response(404)

    def _ia(self, req):
        path = unquote(req.url.path)
        if path == "/advancedsearch.php":
            q = parse_qs(urlparse(str(req.url)).query)["q"][0].lower()
            docs = []
            for ident, item in self.ia_items.items():
                m = item["metadata"]
                titles = [f["title"].lower() for f in item["files"] if "title" in f] + [m["title"].lower()]
                creator_ok = f'creator:("{m["creator"].lower()}")' in q if "creator:" in q else True
                if creator_ok and any(f'("{t.split(" (")[0]}")' in q or f'("{t}")' in q for t in titles):
                    docs.append({"identifier": ident, "title": m["title"], "creator": m["creator"]})
            if "mediatype:(audio)" == q:
                docs = [{"identifier": "x"}]
            return httpx.Response(200, json={"responseHeader": {"status": 0}, "response": {"numFound": len(docs), "docs": docs}})
        if path.startswith("/metadata/"):
            item = self.ia_items.get(path.split("/", 2)[2])
            if not item:
                return httpx.Response(200, json={})
            files = [{k: v for k, v in f.items() if k != "_audio"} for f in item["files"]]
            return httpx.Response(200, json={"metadata": item["metadata"], "files": files})
        if path.startswith("/download/"):
            _, _, ident, name = path.split("/", 3)
            item = self.ia_items.get(ident)
            f = next((f for f in (item or {}).get("files", []) if f["name"] == name), None)
            if not f:
                return httpx.Response(404)
            if req.url.host == "archive.org":  # IA redirects downloads to a storage node
                return httpx.Response(302, headers={"location": f"https://ia800100.us.archive.org/1/items/{ident}/{name}"})
            return httpx.Response(200, content=self.audio[f["_audio"]], headers={"content-type": "audio/flac"})
        if path.startswith("/1/items/"):
            _, _, _, ident, name = path.split("/", 4)
            f = next(f for f in self.ia_items[ident]["files"] if f["name"] == name)
            return httpx.Response(200, content=self.audio[f["_audio"]], headers={"content-type": "application/octet-stream"})
        return httpx.Response(404)

    def _jamendo(self, req):
        q = dict(req.url.params)
        if q.get("client_id") != "jam":
            return httpx.Response(200, json={"headers": {"status": "failed", "code": 5, "error_message": "Invalid client id",
                                                         "results_count": 0}, "results": []})
        s = q.get("search", "").lower()
        res = ([t for t in self.jamendo_tracks if t["artist_name"].lower() in s or t["name"].lower() in s]
               if "search" in q else self.jamendo_tracks[:1])
        if q.get("id"):
            res = [t for t in self.jamendo_tracks if t["id"] == q["id"]]
        return httpx.Response(200, json={"headers": {"status": "success", "code": 0, "results_count": len(res)},
                                         "results": res})
