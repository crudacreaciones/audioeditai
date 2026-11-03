"""A minimal in-process fake of Spotify's Accounts service + Web API, used by tests and demos."""
from __future__ import annotations

import base64
import hashlib
import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CLIENT_ID = "test-client-id"


def _img(seed: str) -> list[dict]:
    # inline SVG covers so nothing hits the network
    hue = int(hashlib.md5(seed.encode()).hexdigest()[:2], 16) * 360 // 255
    svg = (f"<svg xmlns='http://www.w3.org/2000/svg' width='300' height='300'><defs><linearGradient id='g' x1='0' y1='0' "
           f"x2='1' y2='1'><stop offset='0' stop-color='hsl({hue},70%,55%)'/><stop offset='1' "
           f"stop-color='hsl({(hue + 60) % 360},70%,25%)'/></linearGradient></defs><rect width='300' height='300' "
           f"fill='url(#g)'/></svg>")
    url = "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()
    return [{"url": url, "width": 300, "height": 300}]


ALBUMS = {
    "alb1": {"id": "alb1", "name": "Tonos de Prueba", "artists": [{"id": "art1", "name": "Sine Wave Orchestra"}],
             "release_date": "2024-01-01", "total_tracks": 2, "images": _img("alb1"),
             "external_urls": {"spotify": "https://open.spotify.com/album/alb1"}},
    "alb2": {"id": "alb2", "name": "Ruido Blanco", "artists": [{"id": "art2", "name": "Los Generadores"}],
             "release_date": "2023-05-05", "total_tracks": 1, "images": _img("alb2"),
             "external_urls": {"spotify": "https://open.spotify.com/album/alb2"}},
}

TRACKS = {
    "trk1": {"id": "trk1", "name": "La Primera Onda", "duration_ms": 3000, "album": "alb1", "artists": ["art1"]},
    "trk2": {"id": "trk2", "name": "Segundo Armónico", "duration_ms": 4000, "album": "alb1", "artists": ["art1"]},
    "trk3": {"id": "trk3", "name": "Estática Nocturna", "duration_ms": 2000, "album": "alb2", "artists": ["art2"]},
    "trk4": {"id": "trk4", "name": "Canción Sin Archivo", "duration_ms": 200000, "album": "alb2", "artists": ["art2"]},
}

ARTISTS = {
    "art1": {"id": "art1", "name": "Sine Wave Orchestra", "genres": ["electronic", "ambient"], "images": _img("art1"),
             "external_urls": {"spotify": "https://open.spotify.com/artist/art1"}},
    "art2": {"id": "art2", "name": "Los Generadores", "genres": ["noise"], "images": _img("art2"),
             "external_urls": {"spotify": "https://open.spotify.com/artist/art2"}},
}

PLAYLISTS = {
    "pl1": {"id": "pl1", "name": "Mis tonos favoritos", "tracks": ["trk1", "trk2", "trk3"]},
    "pl2": {"id": "pl2", "name": "Para convertir", "tracks": ["trk3", "trk4"]},
}


def full_track(tid: str, with_album: bool = True) -> dict:
    t = TRACKS[tid]
    a = ALBUMS[t["album"]]
    out = {"id": tid, "type": "track", "name": t["name"], "duration_ms": t["duration_ms"], "uri": f"spotify:track:{tid}",
           "explicit": False, "external_urls": {"spotify": f"https://open.spotify.com/track/{tid}"},
           "external_ids": {"isrc": f"ES{tid.upper()}0001"},
           "artists": [{"id": x, "name": ARTISTS[x]["name"]} for x in t["artists"]]}
    if with_album:
        out["album"] = {k: a[k] for k in ("id", "name", "images", "artists", "release_date", "external_urls")}
    return out


class FakeSpotify:
    def __init__(self):
        self.codes: dict[str, str] = {}  # code -> code_challenge
        self.tokens: set[str] = set()
        self.refresh_tokens: set[str] = set()
        self.counter = 0
        self.requests: list[str] = []
        self.legacy_playlist_endpoint = False
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.port = self.server.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self) -> "FakeSpotify":
        self.thread.start()
        return self

    def stop(self) -> None:
        self.server.shutdown()

    def issue_code(self, challenge: str) -> str:
        self.counter += 1
        code = f"code{self.counter}"
        self.codes[code] = challenge
        return code

    def expire_all_access_tokens(self) -> None:
        self.tokens.clear()

    def _handler(self):
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, code: int, obj) -> None:
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            # --- accounts ---
            def do_GET(self):
                u = urllib.parse.urlparse(self.path)
                q = dict(urllib.parse.parse_qsl(u.query))
                fake.requests.append(u.path)
                if u.path == "/authorize":
                    # auto-approve and redirect back like Spotify would
                    if q.get("client_id") != CLIENT_ID:
                        return self._json(400, {"error": "invalid_client"})
                    code = fake.issue_code(q["code_challenge"])
                    loc = q["redirect_uri"] + "?" + urllib.parse.urlencode({"code": code, "state": q["state"]})
                    self.send_response(302)
                    self.send_header("Location", loc)
                    self.end_headers()
                    return
                if u.path.startswith("/v1/"):
                    auth = self.headers.get("Authorization", "")
                    if auth.removeprefix("Bearer ") not in fake.tokens:
                        return self._json(401, {"error": {"status": 401, "message": "The access token expired"}})
                    return self._api(u.path[3:], q)
                self._json(404, {"error": "not found"})

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                form = dict(urllib.parse.parse_qsl(self.rfile.read(n).decode()))
                if self.path != "/api/token":
                    return self._json(404, {})
                if form.get("client_id") != CLIENT_ID:
                    return self._json(400, {"error": "invalid_client"})
                if form.get("grant_type") == "authorization_code":
                    challenge = fake.codes.pop(form.get("code", ""), None)
                    calc = base64.urlsafe_b64encode(
                        hashlib.sha256(form.get("code_verifier", "").encode()).digest()).rstrip(b"=").decode()
                    if not challenge or challenge != calc:
                        return self._json(400, {"error": "invalid_grant"})
                elif form.get("grant_type") == "refresh_token":
                    if form.get("refresh_token") not in fake.refresh_tokens:
                        return self._json(400, {"error": "invalid_grant"})
                else:
                    return self._json(400, {"error": "unsupported_grant_type"})
                fake.counter += 1
                at, rt = f"at{fake.counter}", f"rt{fake.counter}"
                fake.tokens.add(at)
                fake.refresh_tokens.add(rt)
                self._json(200, {"access_token": at, "token_type": "Bearer", "expires_in": 3600,
                                 "refresh_token": rt, "scope": "playlist-read-private"})

            def _api(self, path: str, q: dict):
                parts = path.strip("/").split("/")
                if path == "/me":
                    return self._json(200, {"id": "demo_user", "display_name": "Usuario Demo", "product": "premium",
                                            "images": []})
                if path == "/search":
                    term = q.get("q", "").lower()
                    types = q.get("type", "track").split(",")
                    res = {}
                    if "track" in types:
                        items = [full_track(t) for t, v in TRACKS.items() if term in v["name"].lower()
                                 or any(term in ARTISTS[a]["name"].lower() for a in v["artists"]) or term == "*"]
                        res["tracks"] = {"items": items, "total": len(items)}
                    if "album" in types:
                        items = [a for a in ALBUMS.values() if term in a["name"].lower() or term == "*"
                                 or term in a["artists"][0]["name"].lower()]
                        res["albums"] = {"items": items, "total": len(items)}
                    if "artist" in types:
                        items = [a for a in ARTISTS.values() if term in a["name"].lower() or term == "*"]
                        res["artists"] = {"items": items, "total": len(items)}
                    return self._json(200, res)
                if path == "/me/playlists":
                    items = [{"id": p["id"], "name": p["name"], "owner": {"display_name": "Usuario Demo"},
                              "images": _img(p["id"]), "items": {"total": len(p["tracks"])},
                              "external_urls": {"spotify": ""}} for p in PLAYLISTS.values()]
                    return self._json(200, {"items": items, "total": len(items), "next": None})
                if len(parts) == 3 and parts[0] == "playlists" and parts[1] in PLAYLISTS:
                    if parts[2] == "items" and fake.legacy_playlist_endpoint:
                        return self._json(404, {"error": {"status": 404, "message": "Not found"}})
                    key = "item" if parts[2] == "items" else "track"
                    items = [{key: full_track(t)} for t in PLAYLISTS[parts[1]]["tracks"]]
                    return self._json(200, {"items": items, "next": None, "total": len(items)})
                if path == "/me/tracks":
                    return self._json(200, {"items": [{"track": full_track("trk2")}], "next": None})
                if len(parts) == 2 and parts[0] == "albums" and parts[1] in ALBUMS:
                    a = dict(ALBUMS[parts[1]])
                    a["tracks"] = {"items": [full_track(t, False) for t, v in TRACKS.items() if v["album"] == parts[1]],
                                   "next": None}
                    return self._json(200, a)
                if len(parts) >= 2 and parts[0] == "artists" and parts[1] in ARTISTS:
                    if len(parts) == 3 and parts[2] == "albums":
                        items = [a for a in ALBUMS.values() if a["artists"][0]["id"] == parts[1]]
                        return self._json(200, {"items": items, "next": None})
                    return self._json(200, ARTISTS[parts[1]])
                self._json(404, {"error": {"status": 404, "message": "Not found"}})

        return H
