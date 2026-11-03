"""Verify WAVIFY against the REAL services (no simulations).

    SPOTIFY_CLIENT_ID=… SPOTIFY_CLIENT_SECRET=… [JAMENDO_CLIENT_ID=…] \
    python scripts/verify_live.py "https://open.spotify.com/track/…" [more links…]

Prints, for each provider, whether its real API answered, and for each link the full pipeline outcome
(identified track, candidates per provider with their availability, and the generated MP3 if any).
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from wavify.config import Settings  # noqa: E402
from wavify.jobs import JobManager  # noqa: E402
from wavify.providers.registry import ProviderRegistry  # noqa: E402
from wavify.search import SearchCoordinator  # noqa: E402
from wavify.spotify import SpotifyClient  # noqa: E402


async def main(links: list[str]) -> int:
    s = Settings.from_env()
    s.tmp_dir = Path("live-output")
    s.file_ttl = 10 ** 9
    async with httpx.AsyncClient(timeout=30, headers={"User-Agent": "WAVIFY/1.0 live-check"}) as http:
        reg = ProviderRegistry(s, http)
        reg.load_from_settings()
        print("== Proveedores (peticiones reales) ==")
        for p in await reg.check_all():
            print(f"  {p['name']:<18} estado={p['status']:<15} faltan={p['missing_configuration']} "
                  f"errores={[e['error'] for e in p['errors']]}")
        sp = SpotifyClient(http, s)
        jm = JobManager(s, http, sp, SearchCoordinator(reg, s), reg)
        jm.start()
        for link in links:
            print(f"\n== {link}")
            job = jm.create(link, 320)
            await job.task
            print(json.dumps(job.public(include_candidates=True), ensure_ascii=False, indent=2)[:6000])
            if job.file_path:
                print(f"  MP3 generado: {job.file_path.resolve()}")
        await jm.stop()
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(asyncio.run(main(sys.argv[1:])))
