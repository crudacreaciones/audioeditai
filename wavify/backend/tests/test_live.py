"""Real-network tests. Run with:  pytest -m live   (needs network access + credentials in the environment)."""
import os

import httpx
import pytest

from conftest import run
from wavify.config import Settings
from wavify.providers.base import TrackQuery
from wavify.providers.internet_archive import InternetArchiveProvider
from wavify.providers.jamendo import JamendoProvider
from wavify.spotify import SpotifyClient

pytestmark = pytest.mark.live


def test_live_internet_archive():
    async def go():
        async with httpx.AsyncClient(timeout=30) as http:
            ia = InternetArchiveProvider(http, Settings())
            await ia.health_check()
            return await ia.search(TrackQuery(title="Moonlight Sonata", artists=["Beethoven"]))
    cands = run(go())
    print([(c.title, c.artist, c.availability.value, c.license.name if c.license else None) for c in cands[:10]])


@pytest.mark.skipif(not os.environ.get("JAMENDO_CLIENT_ID"), reason="JAMENDO_CLIENT_ID not set")
def test_live_jamendo():
    async def go():
        async with httpx.AsyncClient(timeout=30) as http:
            j = JamendoProvider(http, Settings.from_env())
            await j.health_check()
            return await j.search(TrackQuery(title="Wholesome", artists=["Kevin MacLeod"]))
    print([(c.title, c.artist, c.availability.value) for c in run(go())])


@pytest.mark.skipif(not os.environ.get("SPOTIFY_CLIENT_SECRET"), reason="Spotify credentials not set")
def test_live_spotify():
    async def go():
        async with httpx.AsyncClient(timeout=30) as http:
            return await SpotifyClient(http, Settings.from_env()).get_track("4uLU6hMCjMI75M1A2tKUQC")
    t = run(go())
    assert t.title and t.artists
    print(t)
