import os
import subprocess
import time

import pytest
from fastapi.testclient import TestClient

from fakes import COVER_ONLY_ID, OTHER_ID, SPOTIFY_ID, STREAM_ONLY_ID, FakeInternet
from wavify.api import create_app

URL = f"https://open.spotify.com/track/{SPOTIFY_ID}?si=abc"


@pytest.fixture()
def env(audio, settings):
    fake = FakeInternet(audio)
    app = create_app(settings, transport=fake.transport())
    with TestClient(app) as c:
        c.fake, c.settings, c.state = fake, settings, app.state.wavify
        yield c


def wait(c, jid, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        j = c.get(f"/api/v1/jobs/{jid}", params={"details": True}).json()
        if j["final"]:
            return j
        time.sleep(0.05)
    raise TimeoutError(j)


def start(c, url=URL, bitrate=320):
    r = c.post("/api/v1/jobs", json={"url": url, "bitrate": bitrate})
    assert r.status_code == 202, r.text
    return wait(c, r.json()["id"])


def test_health_and_providers(env):
    h = env.get("/api/v1/health").json()
    assert h["ok"] and h["spotify_configured"] and h["active_providers"] == 2
    ps = {p["id"]: p for p in env.get("/api/v1/providers").json()}
    assert ps["internet_archive"]["status"] == "ok" and ps["jamendo"]["capabilities"]["requires_credentials"]


def test_full_flow_link_to_mp3(env, tmp_path):
    j = start(env)
    assert j["stage"] == "ready", j
    assert j["track"]["title"] == "Luz de Mañana" and j["track"]["artists"] == ["Aurora Libre"]
    sel = j["selected"]
    assert sel["provider"] == "internet_archive" and sel["lossless"] and sel["license"]["name"] == "CC BY-SA 4.0"
    # Jamendo's live version was found but correctly NOT accepted
    statuses = {(c["provider"], c["title"]): c["availability"] for c in j["candidates"]}
    assert statuses[("jamendo", "Luz de Mañana (Live)")] == "unverified_match"
    assert j["summary"]["evaluated"] == 2 and j["summary"]["verified"] == 1
    f = j["file"]
    assert f["name"] == "Aurora Libre - Luz de Mañana.mp3" and f["bitrate_kbps"] == 320
    r = env.get(f["download_path"])
    assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg"
    assert "attachment" in r.headers["content-disposition"]
    out = tmp_path / "saved.mp3"
    out.write_bytes(r.content)
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name:format_tags", "-of",
                            "default=nw=1", str(out)], capture_output=True, text=True).stdout
    assert "codec_name=mp3" in probe and "TAG:title=Luz de Mañana" in probe and "CC BY-SA 4.0" in probe
    # source file removed after conversion, only the MP3 remains
    job_dir = env.settings.tmp_dir / j["id"]
    assert [p.name for p in job_dir.iterdir()] == ["output.mp3"]


def test_wrong_token_and_expiry_cleanup(env):
    j = start(env)
    assert env.get(f"/api/v1/jobs/{j['id']}/file", params={"token": "nope"}).status_code == 404
    jm = env.state["jobs"]
    assert jm.cleanup(now=time.time() + env.settings.file_ttl + 1) == 1
    assert not (env.settings.tmp_dir / j["id"]).exists()
    assert env.get(j["file"]["download_path"]).status_code == 404


def test_not_found_anywhere(env):
    j = start(env, f"https://open.spotify.com/track/{OTHER_ID}")
    # IA has the song but without a licence -> found, verified, NOT downloadable
    assert j["stage"] == "no_results" and j["summary"]["reason"] == "not_downloadable"
    assert "no hay una versión descargable autorizada" in j["message"]
    assert j["selected"]["availability"] == "license_incompatible" and j["file"] is None


def test_stream_only(env):
    j = start(env, f"https://open.spotify.com/track/{STREAM_ONLY_ID}")
    assert j["stage"] == "no_results" and j["selected"]["availability"] == "stream_only"


def test_only_unreliable_matches(env):
    j = start(env, f"https://open.spotify.com/track/{COVER_ONLY_ID}")
    assert j["stage"] == "no_results" and j["summary"]["reason"] == "no_reliable_match"
    assert j["candidates"][0]["match_details"]["reasons"] == ["Otro artista o intérprete"]


def test_nothing_found(env):
    env.fake.ia_items.clear()
    env.fake.jamendo_tracks.clear()
    j = start(env)
    assert j["stage"] == "no_results" and j["summary"]["reason"] == "not_found"


def test_provider_down_does_not_stop_others(env):
    env.fake.down.add("api.jamendo.com")
    j = start(env)
    assert j["stage"] == "ready"
    assert {p["id"]: p["ok"] for p in j["summary"]["providers"]} == {"internet_archive": True, "jamendo": False}


def test_all_providers_down(env):
    env.fake.down.update({"archive.org", "api.jamendo.com"})
    j = start(env)
    assert j["stage"] == "error" and j["error"]["code"] == "providers_unavailable" and j["error"]["retryable"]


def test_spotify_without_credentials(env):
    env.settings.spotify_client_id = ""
    j = start(env)
    assert j["stage"] == "error" and j["error"]["code"] == "spotify_not_configured" and not j["error"]["retryable"]


def test_track_not_found_and_invalid_links(env):
    j = start(env, "https://open.spotify.com/track/" + "Z" * 22)
    assert j["error"]["code"] == "track_not_found"
    r = env.post("/api/v1/jobs", json={"url": "https://youtube.com/watch?v=x"})
    assert r.status_code == 422 and "Solo se admiten" in r.json()["detail"]
    assert env.post("/api/v1/jobs", json={"url": URL, "bitrate": 999}).status_code == 422


def test_short_link_flow(env):
    assert start(env, "https://spotify.link/abc123")["stage"] == "ready"


def test_low_quality_source_is_not_inflated(env):
    # only an MP3 128 kbps version available -> output stays 128 kbps and the note explains why
    for f in env.fake.ia_items["aurora-libre-cielos"]["files"]:
        if f["format"] == "Flac":
            f["format"] = "JPEG"
    j = start(env)
    assert j["stage"] == "ready" and j["file"]["bitrate_kbps"] == 128 and "no mejoraría" in j["file"]["note"]


def test_corrupt_download(env):
    item = env.fake.ia_items["aurora-libre-cielos"]
    env.fake.audio["flac6"] = b"\x00garbage" * 300
    import hashlib
    item["files"][0]["md5"] = hashlib.md5(env.fake.audio["flac6"]).hexdigest()
    item["files"][0]["size"] = str(len(env.fake.audio["flac6"]))
    j = start(env)
    assert j["stage"] == "error" and j["error"]["code"] == "conversion_failed" and "dañado" in j["error"]["message"]
    assert not (env.settings.tmp_dir / j["id"]).exists()


def test_cancel(env):
    item = env.fake.ia_items["aurora-libre-cielos"]
    item["files"][0]["_audio"] = "long_flac"
    data = env.fake.audio["long_flac"]
    import hashlib
    item["files"][0].update(md5=hashlib.md5(data).hexdigest(), size=str(len(data)), length="900")
    env.fake.spotify_tracks[SPOTIFY_ID]["duration_ms"] = 900_000
    jid = env.post("/api/v1/jobs", json={"url": URL}).json()["id"]
    end = time.time() + 60
    while env.get(f"/api/v1/jobs/{jid}").json()["stage"] != "converting" and time.time() < end:
        time.sleep(0.05)
    assert env.post(f"/api/v1/jobs/{jid}/cancel").json()["cancelled"]
    j = wait(env, jid)
    assert j["stage"] == "cancelled" and not (env.settings.tmp_dir / jid).exists()
    assert not env.post(f"/api/v1/jobs/{jid}/cancel").json()["cancelled"]


def test_rate_limit(env):
    env.state["limiter"].per_minute = 2
    codes = [env.post("/api/v1/jobs", json={"url": URL}).status_code for _ in range(3)]
    assert codes == [202, 202, 429]


def test_admin_endpoints(env):
    assert env.post("/api/v1/providers/jamendo/disable").status_code == 403
    env.settings.admin_token = "s3cret"
    r = env.post("/api/v1/providers/jamendo/disable", headers={"X-Admin-Token": "s3cret"})
    assert r.json()["status"] == "disabled"
    j = start(env)
    assert [p["id"] for p in j["summary"]["providers"]] == ["internet_archive"]
