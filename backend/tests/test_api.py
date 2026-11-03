import os
import urllib.parse

import httpx

from conftest import wait_for


def do_import(client, paths, **kw):
    job = client.post("/api/import", json={"paths": [str(p) for p in paths], **kw}).json()
    return wait_for(lambda: (j := client.get(f"/api/import/{job['id']}").json())["status"] in ("done", "failed",
                                                                                              "cancelled") and j)


def wait_jobs(client, ids, timeout=120):
    def done():
        jobs = [client.get(f"/api/conversions/{i}").json() for i in ids]
        return jobs if all(j["status"] not in ("queued", "running") for j in jobs) else None
    return wait_for(done, timeout)


def connect_spotify(client):
    client.put("/api/settings", json={"spotify_client_id": client.client_id})
    url = client.get("/api/spotify/login").json()["url"]
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
    assert q["code_challenge_method"] == "S256" and q["redirect_uri"].startswith("http://127.0.0.1:")
    r = httpx.get(url, follow_redirects=False)  # fake Spotify auto-approves and redirects
    loc = urllib.parse.urlparse(r.headers["location"])
    page = client.get(f"{loc.path}?{loc.query}")
    assert "Spotify conectado" in page.text, page.text
    return client.get("/api/spotify/status").json()


# ---------------------------------------------------------------------------
def test_health_and_system(client):
    assert client.get("/api/health").json()["ok"]
    s = client.get("/api/system").json()
    assert s["ffmpeg"]["ffmpeg"] and s["options"]["sample_rates"] == [44100, 48000, 88200, 96000, 192000]
    assert client.get("/").status_code == 200  # frontend served


def test_security_middleware(client):
    from fastapi.testclient import TestClient
    raw = TestClient(client.app)
    assert raw.post("/api/import", json={"paths": ["/x"]}).status_code == 403  # missing X-SWC header
    assert raw.get("/api/health", headers={"host": "evil.example.com"}).status_code == 403


def test_import_folder_duplicates_errors(client, media_dir):
    job = do_import(client, [media_dir])
    assert job["status"] == "done"
    assert len(job["imported"]) == 6
    assert len(job["duplicates"]) == 1 and job["duplicates"][0]["path"].endswith("copia.mp3")
    assert len(job["errors"]) == 1 and job["errors"][0]["path"].endswith("roto.mp3")
    lib = client.get("/api/library").json()
    assert lib["total"] == 6
    by_title = {t["title"]: t for t in lib["items"]}
    flac = by_title["Segundo Armónico"]
    assert flac["sample_rate"] == 96000 and flac["format"] == "flac" and flac["album"] == "Tonos de Prueba"
    raw_aac = next(t for t in lib["items"] if t["format"] == "aac")
    assert raw_aac["artist"] == "Codec Lab" and raw_aac["title"] == "Crudo"  # guessed from filename

    # re-import is idempotent (updates, no new rows)
    job2 = do_import(client, [media_dir])
    assert len(job2["imported"]) == 0 and len(job2["updated"]) == 6
    # importing a single file + a missing path
    job3 = do_import(client, [media_dir / "otros" / "tono.m4a", "/no/existe"])
    assert len(job3["updated"]) == 1 and any("no existe" in e["error"] for e in job3["errors"])


def test_import_keep_duplicates_and_detect(client, media_dir):
    do_import(client, [media_dir], skip_duplicates=False)
    groups = client.get("/api/library/duplicates").json()
    assert any(g["kind"] == "exact" and len(g["items"]) == 2 for g in groups)


def test_probable_duplicates(client, media_dir, tmp_path):
    from conftest import make_tone
    make_tone(tmp_path / "v2.flac", 3, 500, ["-c:a", "flac"],
              {"title": "La Primera Onda (Remastered 2020)", "artist": "Sine Wave Orchestra"})
    do_import(client, [media_dir, tmp_path / "v2.flac"])
    groups = client.get("/api/library/duplicates").json()
    assert any(g["kind"] == "probable" for g in groups)


def test_library_search_facets_edit(client, media_dir, tmp_path):
    import shutil
    work = tmp_path / "lib"
    shutil.copytree(media_dir, work)
    do_import(client, [work])
    assert client.get("/api/library", params={"q": "armónico"}).json()["total"] == 1
    assert client.get("/api/library", params={"artist": "Codec Lab"}).json()["total"] == 3
    assert client.get("/api/library", params={"genre": "Noise"}).json()["total"] == 1
    facets = client.get("/api/library/facets").json()
    assert {f["value"] for f in facets["album"]} >= {"Tonos de Prueba", "Ruido Blanco"}

    t = client.get("/api/library", params={"q": "Tono AAC"}).json()["items"][0]
    r = client.put(f"/api/library/{t['id']}", json={"values": {"title": "Tono Editado", "genre": "Jazz"},
                                                   "write_to_file": True})
    assert r.status_code == 200 and r.json()["title"] == "Tono Editado"
    assert r.json()["file_hash"] != t["file_hash"]  # tags rewritten in the file
    from swc.services.metadata import read_tags
    assert read_tags(t["path"])["title"] == "Tono Editado"
    # stream preview with HTTP range support
    s = client.get(f"/api/library/{t['id']}/stream", headers={"Range": "bytes=0-99"})
    assert s.status_code == 206 and len(s.content) == 100
    # remove from library (file kept)
    assert client.post("/api/library/remove", json={"ids": [t["id"]]}).json()["removed"] == 1
    assert os.path.exists(t["path"])


def test_batch_conversion_verify_export(client, media_dir, tmp_path):
    do_import(client, [media_dir])
    ids = [t["id"] for t in client.get("/api/library").json()["items"]]
    out = tmp_path / "wav"
    r = client.post("/api/conversions", json={"track_ids": ids, "sample_rate": 96000, "bit_depth": "24",
                                              "channels": 2, "output_dir": str(out)}).json()
    jobs = wait_jobs(client, r["job_ids"])
    assert all(j["status"] == "done" and j["verified"] and j["output_exists"] for j in jobs), jobs
    names = sorted(os.listdir(out))
    assert "Sine Wave Orchestra - La Primera Onda.wav" in names and len(names) == 6
    for j in jobs:
        assert j["verify_report"]["info"]["sample_rate"] == 96000
        assert j["verify_report"]["info"]["codec"] == "pcm_s24le"

    # convert same tracks again -> unique names, no overwrite
    r2 = client.post("/api/conversions", json={"track_ids": ids[:1], "sample_rate": 44100, "bit_depth": "16",
                                               "channels": 1, "output_dir": str(out)}).json()
    j2 = wait_jobs(client, r2["job_ids"])[0]
    assert j2["output_path"].endswith("(1).wav")

    # preview of WAV output
    assert client.get(f"/api/conversions/{jobs[0]['id']}/stream").status_code == 200
    # manual re-verification
    assert client.post(f"/api/conversions/{jobs[0]['id']}/verify").json()["ok"]

    # export to another folder with naming pattern
    dest = tmp_path / "export"
    res = client.post("/api/export", json={"conversion_ids": [j["id"] for j in jobs], "dest_dir": str(dest),
                                           "naming_pattern": "{album} - {title}"}).json()
    assert len(res["exported"]) == 6 and not res["errors"]
    assert "Tonos de Prueba - Segundo Armónico.wav" in os.listdir(dest)

    dash = client.get("/api/dashboard").json()
    assert dash["conversions"]["done"] == 7 and dash["library"]["tracks"] == 6
    logs = client.get("/api/logs", params={"category": "convert"}).json()
    assert any("Convertido" in log["message"] for log in logs)


def test_cancel_and_retry(client, long_flac, tmp_path):
    do_import(client, [long_flac])
    tid = client.get("/api/library").json()["items"][0]["id"]
    client.put("/api/settings", json={"concurrency": 1})
    r = client.post("/api/conversions", json={"track_ids": [tid, tid], "sample_rate": 192000, "bit_depth": "32f",
                                              "channels": 2, "output_dir": str(tmp_path / "o")}).json()
    first, second = r["job_ids"]
    wait_for(lambda: client.get(f"/api/conversions/{first}").json()["status"] == "running")
    assert client.post("/api/conversions/cancel-all").json()["cancelled"] >= 1
    jobs = wait_jobs(client, [first, second])
    assert {j["status"] for j in jobs} == {"cancelled"}
    assert not any(j["output_exists"] for j in jobs)
    assert not [f for f in os.listdir(tmp_path / "o") if f.endswith((".wav", ".part"))]
    # retry a cancelled job and let it finish
    new = client.post(f"/api/conversions/{second}/retry").json()["job_id"]
    done = wait_jobs(client, [new], timeout=240)[0]
    assert done["status"] == "done" and done["verified"]
    assert client.post(f"/api/conversions/{new}/retry").status_code == 400


def test_conversion_errors(client, media_dir, tmp_path):
    import shutil
    f = tmp_path / "t.mp3"
    shutil.copy(media_dir / "Sine Wave Orchestra - La Primera Onda.mp3", f)
    do_import(client, [f])
    tid = client.get("/api/library").json()["items"][0]["id"]
    assert client.post("/api/conversions", json={"track_ids": []}).status_code == 400
    assert client.post("/api/conversions", json={"track_ids": [tid], "sample_rate": 22050}).status_code == 422
    assert client.post("/api/conversions", json={"track_ids": [999]}).status_code == 404
    f.unlink()
    assert client.post("/api/conversions", json={"track_ids": [tid]}).status_code == 422


def test_settings_validation(client, tmp_path):
    s = client.put("/api/settings", json={"default_sample_rate": 48000, "output_dir": str(tmp_path / "x"),
                                          "unknown": 1}).json()
    assert s["default_sample_rate"] == 48000 and os.path.isdir(tmp_path / "x") and "unknown" not in s
    assert client.put("/api/settings", json={"default_bit_depth": "12"}).status_code == 400
    assert s["spotify_redirect_uri"] == "http://127.0.0.1:8765/api/spotify/callback"


def test_fs_browser(client, media_dir):
    r = client.get("/api/fs/list", params={"path": str(media_dir)}).json()
    assert {d["name"] for d in r["dirs"]} >= {"album", "otros", "copias"}
    assert [f["name"] for f in r["files"]] == ["Sine Wave Orchestra - La Primera Onda.mp3"]
    assert client.get("/api/fs/list", params={"path": "/no/existe"}).status_code == 404


# ---- Spotify ---------------------------------------------------------------
def test_spotify_requires_config_and_connection(client):
    assert client.get("/api/spotify/login").status_code == 400
    assert client.get("/api/spotify/search", params={"q": "x"}).status_code == 401
    st = client.get("/api/spotify/status").json()
    assert not st["configured"] and not st["connected"]


def test_spotify_oauth_and_catalog(client):
    st = connect_spotify(client)
    assert st["connected"] and st["user"]["name"] == "Usuario Demo"

    res = client.get("/api/spotify/search", params={"q": "onda", "type": "track"}).json()
    assert [t["name"] for t in res["tracks"]] == ["La Primera Onda"]
    t = res["tracks"][0]
    assert t["artists"] == "Sine Wave Orchestra" and t["album"] == "Tonos de Prueba" and t["duration_ms"] == 3000
    assert t["image_url"].startswith("data:image/svg")
    albums = client.get("/api/spotify/search", params={"q": "*", "type": "album"}).json()["albums"]
    assert len(albums) == 2
    artists = client.get("/api/spotify/search", params={"q": "generadores", "type": "artist"}).json()["artists"]
    assert artists[0]["genres"] == ["noise"]

    pls = client.get("/api/spotify/playlists").json()["items"]
    assert [p["name"] for p in pls] == ["Mis tonos favoritos", "Para convertir"] and pls[0]["total"] == 3
    assert len(client.get("/api/spotify/playlists/pl1").json()) == 3
    client.fake.legacy_playlist_endpoint = True  # falls back to /tracks
    assert len(client.get("/api/spotify/playlists/pl2").json()) == 2
    assert client.get("/api/spotify/saved").json()[0]["id"] == "trk2"
    alb = client.get("/api/spotify/albums/alb1").json()
    assert len(alb["tracks"]) == 2 and alb["tracks"][0]["album"] == "Tonos de Prueba"
    art = client.get("/api/spotify/artists/art1").json()
    assert art["artist"]["name"] == "Sine Wave Orchestra" and art["albums"][0]["id"] == "alb1"

    # expired access token -> transparent refresh
    client.fake.expire_all_access_tokens()
    assert client.get("/api/spotify/search", params={"q": "estática"}).status_code == 200

    # logout
    client.post("/api/spotify/logout")
    assert not client.get("/api/spotify/status").json()["connected"]


def test_spotify_callback_rejects_bad_state(client):
    client.put("/api/settings", json={"spotify_client_id": client.client_id})
    page = client.get("/api/spotify/callback", params={"code": "x", "state": "forged"})
    assert "No se pudo conectar" in page.text
    page = client.get("/api/spotify/callback", params={"error": "access_denied"})
    assert "access_denied" in page.text


def test_worklist_and_matching(client, media_dir):
    connect_spotify(client)
    do_import(client, [media_dir])
    tracks = client.get("/api/spotify/playlists/pl1").json() + client.get("/api/spotify/playlists/pl2").json()
    assert client.post("/api/worklist", json=tracks).json()["added"] == 5
    wl = client.get("/api/worklist").json()
    assert len(wl) == 4  # trk3 deduplicated

    res = client.post("/api/worklist/match").json()
    linked = {m["spotify_id"] for m in res["linked"]}
    assert linked == {"trk1", "trk2", "trk3"} and res["unmatched"] == 1
    wl = {w["id"]: w for w in client.get("/api/worklist").json()}
    assert wl["trk1"]["local_track_id"] and not wl["trk4"]["local_track_id"]
    lib = {t["title"]: t for t in client.get("/api/library").json()["items"]}
    assert lib["Segundo Armónico"]["spotify_id"] == "trk2"

    # manual link / unlink
    mono = lib["Onda Mono"]
    cands = client.get(f"/api/library/{mono['id']}/candidates").json()
    assert cands and "score" in cands[0]
    r = client.put(f"/api/library/{mono['id']}/spotify", json={"spotify_id": "trk4"}).json()
    assert r["spotify_id"] == "trk4" and r["spotify_name"] == "Canción Sin Archivo"
    r = client.put(f"/api/library/{mono['id']}/spotify", json={"spotify_id": None}).json()
    assert r["spotify_id"] is None
    assert client.put(f"/api/library/{mono['id']}/spotify", json={"spotify_id": "nope"}).status_code == 404
    assert client.get("/api/worklist/trk4/candidates").status_code == 200

    assert client.post("/api/worklist/remove", json={"ids": ["trk4"]}).json()["removed"] == 1
    assert len(client.get("/api/worklist").json()) == 3


def test_history_clear(client, media_dir, tmp_path):
    do_import(client, [media_dir / "otros" / "mono.wav"])
    tid = client.get("/api/library").json()["items"][0]["id"]
    r = client.post("/api/conversions", json={"track_ids": [tid], "output_dir": str(tmp_path)}).json()
    wait_jobs(client, r["job_ids"])
    assert client.delete("/api/conversions").json()["removed"] == 1
    assert client.get("/api/conversions").json() == []
    assert client.get("/api/logs").json()
    client.delete("/api/logs")
    assert client.get("/api/logs").json() == []


def test_jobs_survive_restart(tmp_path, media_dir):
    """Queued jobs are resumed and 'running' ones marked interrupted after a restart."""
    from swc.app import Services
    from swc.config import load_config
    from swc.db import now

    cfg = load_config(tmp_path / "d")
    svc = Services(cfg)
    svc.library.import_now([str(media_dir / "otros" / "mono.wav")])
    t = svc.library.list()["items"][0]
    for status in ("queued", "running"):
        svc.db.execute("INSERT INTO conversions(batch_id, track_id, source_path, output_path, sample_rate, bit_depth,"
                       " channels, status, created_at) VALUES ('b', ?, ?, ?, 44100, '16', 2, ?, ?)",
                       (t["id"], t["path"], str(tmp_path / f"{status}.wav"), status, now()))
    svc.db.close()
    svc2 = Services(cfg)
    svc2.start()
    try:
        def settled():
            js = svc2.converter.list()
            return js if js and all(j["status"] != "queued" for j in js) else None
        jobs = {os.path.basename(j["output_path"]): j for j in wait_for(settled)}
        assert jobs["running.wav"]["status"] == "failed" and "Interrumpido" in jobs["running.wav"]["error"]
        wait_for(lambda: svc2.converter.get(jobs["queued.wav"]["id"])["status"] == "done")
    finally:
        svc2.stop()
