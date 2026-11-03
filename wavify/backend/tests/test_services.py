import asyncio
import time

import httpx
import pytest

from conftest import run
from fakes import COVER_ONLY_ID, SPOTIFY_ID, FakeInternet
from wavify.downloader import DownloadError, download
from wavify.providers.base import (AudioProvider, Availability, Candidate, Capabilities, DownloadInfo, ProviderError,
                                   TrackQuery)
from wavify.providers.internet_archive import InternetArchiveProvider
from wavify.providers.jamendo import JamendoProvider
from wavify.providers.registry import ProviderRegistry
from wavify.search import SearchCoordinator
from wavify.spotify import SpotifyClient, SpotifyError, parse_link

Q = TrackQuery(title="Luz de Mañana", artists=["Aurora Libre"], album="Cielos Abiertos", duration=6.0)


def client(fake):
    return httpx.AsyncClient(transport=fake.transport())


# ---- providers -----------------------------------------------------------------
def test_internet_archive_search_and_license(audio, settings):
    fake = FakeInternet(audio)

    async def go():
        async with client(fake) as http:
            ia = InternetArchiveProvider(http, settings)
            cands = await ia.search(Q)
            assert len(cands) == 1  # flac + mp3 of the same track collapse to the best file
            c = cands[0]
            assert c.format == "flac" and c.lossless and c.duration == 6.0 and c.artist == "Aurora Libre"
            assert c.availability == Availability.DOWNLOADABLE and c.license.name == "CC BY-SA 4.0"
            info = await ia.get_download(c)
            assert info.url == "https://archive.org/download/aurora-libre-cielos/01%20Luz%20de%20Manana.flac"
            assert info.allowed_hosts == ("archive.org",) and info.md5
            # no licence declared -> incompatible, no download
            nolic = await ia.search(TrackQuery(title="Hit Comercial", artists=["Megastar"]))
            assert nolic[0].availability == Availability.LICENSE_INCOMPATIBLE
            assert await ia.get_download(nolic[0]) is None
            await ia.health_check()
    run(go())


def test_internet_archive_restricted_item(audio, settings):
    fake = FakeInternet(audio)
    fake.ia_items["aurora-libre-cielos"]["metadata"]["access-restricted-item"] = "true"

    async def go():
        async with client(fake) as http:
            c = (await InternetArchiveProvider(http, settings).search(Q))[0]
            assert c.availability == Availability.UNAVAILABLE
    run(go())


def test_jamendo(audio, settings):
    fake = FakeInternet(audio)

    async def go():
        async with client(fake) as http:
            j = JamendoProvider(http, settings)
            stream = await j.search(TrackQuery(title="Solo Escucha", artists=["Banda Cerrada"]))
            assert stream[0].availability == Availability.STREAM_ONLY and await j.get_download(stream[0]) is None
            live = await j.search(Q)
            assert live[0].availability == Availability.DOWNLOADABLE
            info = await j.get_download(live[0])
            assert info.url.startswith("https://prod-1.storage.jamendo.com/") and "jamendo.com" in info.allowed_hosts
            # API without credentials
            settings.jamendo_client_id = ""
            assert not j.configured() and j.missing_configuration() == ["JAMENDO_CLIENT_ID"]
            with pytest.raises(ProviderError):
                await j.search(Q)
            settings.jamendo_client_id = "wrong"
            with pytest.raises(ProviderError, match="Invalid client id"):
                await j.health_check()
    run(go())


# ---- registry + parallel search -----------------------------------------------------
class SlowProvider(AudioProvider):
    name = "Lento"

    def __init__(self, pid, delay=0.5, fail=None, results=1):
        super().__init__(None, None)
        self.id, self.delay, self.fail, self.n, self.calls = pid, delay, fail, results, 0

    def get_capabilities(self):
        return Capabilities()

    async def health_check(self):
        pass

    async def search(self, query):
        self.calls += 1
        await asyncio.sleep(self.delay)
        if self.fail:
            raise self.fail
        return [Candidate(provider=self.id, id=str(i), title=query.title, artist=query.main_artist) for i in range(self.n)]


def make_search(settings, *providers):
    reg = ProviderRegistry(settings, None)
    for p in providers:
        reg.register(p)
    return reg, SearchCoordinator(reg, settings)


def test_parallel_search_and_failure_isolation(settings):
    a, b = SlowProvider("a", 0.5), SlowProvider("b", 0.5)
    down = SlowProvider("down", 0.1, fail=ProviderError("caído"))
    reg, s = make_search(settings, a, b, down)
    t = time.monotonic()
    res = run(s.search_all(Q))
    assert time.monotonic() - t < 0.9, "providers must run concurrently"
    by = {r.provider: r for r in res}
    assert by["a"].ok and by["b"].ok and len(by["a"].candidates) == 1
    assert not by["down"].ok and "caído" in by["down"].error
    assert reg.get("down").status == "degraded" and reg.get("a").status == "ok"


def test_timeout_retries_and_cooldown(settings):
    settings.provider_timeout, settings.provider_retries, settings.provider_failure_threshold = 0.2, 1, 2
    slow = SlowProvider("slow", 1.0)
    flaky = SlowProvider("flaky", 0.0, fail=ProviderError("503", transient=True))
    reg, s = make_search(settings, slow, flaky)
    res = {r.provider: r for r in run(s.search_all(Q))}
    assert "tiempo de espera" in res["slow"].error and slow.calls == 2      # retried once
    assert flaky.calls == 2
    run(s.search_all(TrackQuery(title="otra", artists=["x"])))
    assert reg.get("slow").status == "down" and reg.active() == []          # cooling down, not queried
    assert slow.calls == 4


def test_cache_and_inflight_dedup(settings):
    a = SlowProvider("a", 0.3)
    reg, s = make_search(settings, a)

    async def go():
        r1, r2 = await asyncio.gather(s.search_all(Q), s.search_all(Q))  # identical concurrent queries
        r3 = await s.search_all(Q)                                          # cached
        return r1, r2, r3
    r1, r2, r3 = run(go())
    assert a.calls == 1 and r3[0].cached and r2[0].ok


def test_plugin_registration_and_disable(settings):
    settings.providers = ("wavify.providers.internet_archive:InternetArchiveProvider", "nope.module:X")
    settings.disabled_providers = ("internet_archive",)
    reg = ProviderRegistry(settings, None)
    reg.load_from_settings()  # bad entry logged, not fatal
    assert list(reg.states) == ["internet_archive"] and reg.get("internet_archive").status == "disabled"
    assert reg.active() == []
    reg.set_enabled("internet_archive", True)
    assert reg.get("internet_archive").status == "unverified"  # never "ok" before a real successful call
    with pytest.raises(ValueError):
        reg.register(InternetArchiveProvider(None, settings))


def test_health_check_marks_verified_or_down(audio, settings):
    fake = FakeInternet(audio)

    async def go():
        async with client(fake) as http:
            reg = ProviderRegistry(settings, http)
            reg.load_from_settings()
            fake.down.add("archive.org")
            await reg.check_all()
            assert reg.get("internet_archive").status == "degraded" and reg.get("jamendo").status == "ok"
    run(go())


# ---- spotify ---------------------------------------------------------------------------------
def test_spotify_client(audio, settings):
    fake = FakeInternet(audio)

    async def go():
        async with client(fake) as http:
            sp = SpotifyClient(http, settings)
            t = await sp.get_track(SPOTIFY_ID)
            assert (t.title, t.artists, t.album, t.duration, t.isrc) == ("Luz de Mañana", ["Aurora Libre"],
                                                                           "Cielos Abiertos", 6.0, "ESA012300001")
            assert t.cover_url and t.url.endswith(SPOTIFY_ID)
            fake.tokens.clear()  # token revoked -> transparently renewed
            assert (await sp.get_track(COVER_ONLY_ID)).title == "Canción Famosa"
            with pytest.raises(SpotifyError) as e:
                await sp.get_track("Z" * 22)
            assert e.value.code == "track_not_found"
            link = await sp.resolve_short_link(parse_link("https://spotify.link/abc123"))
            assert link.id == SPOTIFY_ID
            from wavify.spotify import LinkError
            with pytest.raises(LinkError):
                await sp.resolve_short_link(parse_link("https://spotify.link/evil12"))
            # missing / wrong credentials
            settings.spotify_client_secret = ""
            with pytest.raises(SpotifyError) as e:
                await SpotifyClient(http, settings).get_track(SPOTIFY_ID)
            assert e.value.code == "spotify_not_configured" and not e.value.retryable
            settings.spotify_client_secret = "bad"
            with pytest.raises(SpotifyError) as e:
                await SpotifyClient(http, settings).get_track(SPOTIFY_ID)
            assert e.value.code == "spotify_auth"
    run(go())


# ---- downloader ----------------------------------------------------------------------------------
def test_downloader_rules(audio, settings, tmp_path):
    fake = FakeInternet(audio)
    f = fake.ia_items["aurora-libre-cielos"]["files"][0]

    async def go():
        async with client(fake) as http:
            ok = DownloadInfo(url="https://archive.org/download/aurora-libre-cielos/01%20Luz%20de%20Manana.flac",
                              allowed_hosts=("archive.org",), md5=f["md5"])
            progress = []
            p = await download(http, ok, tmp_path / "a.flac", 10_000_000, progress.append)
            assert p.read_bytes() == audio["flac6"] and progress[-1] == 1.0  # followed redirect to *.archive.org
            bad = [
                (DownloadInfo(url="https://evil.example.com/x", allowed_hosts=("archive.org",)), "no pertenece"),
                (DownloadInfo(url="http://archive.org/download/a/b", allowed_hosts=("archive.org",)), "no pertenece"),
                (DownloadInfo(url=ok.url, allowed_hosts=("archive.org",), md5="0" * 32), "MD5"),
                (DownloadInfo(url=ok.url, allowed_hosts=("archive.org",)), "tamaño máximo"),
                (DownloadInfo(url="https://spotify.link/evil12", allowed_hosts=("spotify.link",)), "no autorizado"),
                (DownloadInfo(url="https://archive.org/download/none/none", allowed_hosts=("archive.org",)), "ya no está"),
            ]
            for i, (info, msg) in enumerate(bad):
                limit = 100 if msg == "tamaño máximo" else 10_000_000
                with pytest.raises(DownloadError, match=msg):
                    await download(http, info, tmp_path / f"x{i}", limit)
                assert not (tmp_path / f"x{i}").exists() and not (tmp_path / f"x{i}.part").exists()
            fake.audio["flac6"] = b""
            with pytest.raises(DownloadError, match="vacío"):
                await download(http, DownloadInfo(url=ok.url, allowed_hosts=("archive.org",)), tmp_path / "e", 10**7)
    run(go())
