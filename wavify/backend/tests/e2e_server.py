"""TEST HARNESS ONLY — real WAVIFY backend (real pipeline, matching, FFmpeg conversion) wired to the simulated
external services from tests/fakes.py, so the app can be exercised end-to-end without network access.
Its results are NOT real search results.

    python backend/tests/e2e_server.py --port 8010 --cors http://127.0.0.1:8011
"""
import argparse
import hashlib
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import uvicorn  # noqa: E402

from conftest import _gen  # noqa: E402
from fakes import FakeInternet  # noqa: E402
from wavify.api import create_app  # noqa: E402
from wavify.config import Settings  # noqa: E402

LONG_ID = "0000000000000000000009"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8010)
    ap.add_argument("--cors", default="http://127.0.0.1:8011")
    a = ap.parse_args()
    d = Path(tempfile.mkdtemp(prefix="wavify-e2e-"))
    audio = {
        "flac6": _gen(d / "a.flac", ["-c:a", "flac"], "sine=frequency=440:sample_rate=44100:duration=214"),
        "mp3_128": _gen(d / "c.mp3", ["-c:a", "libmp3lame", "-b:a", "128k"], "sine=frequency=440:duration=214"),
        "long": _gen(d / "l.flac", ["-c:a", "flac"], "sine=frequency=330:sample_rate=96000:duration=1500"),
    }
    fake = FakeInternet(audio)
    for t in fake.spotify_tracks.values():
        t["duration_ms"] = 214_000
    for item in fake.ia_items.values():
        for f in item["files"]:
            if "length" in f:
                f["length"] = "214.0"
    for t in fake.jamendo_tracks:
        t["duration"] = 214
    fake.spotify_tracks[LONG_ID] = fake._sp_track(LONG_ID, "Pieza Larga", ["Aurora Libre"], "Cielos Abiertos",
                                                  1_500_000, "")
    data = audio["long"]
    fake.ia_items["aurora-larga"] = {
        "metadata": {"identifier": "aurora-larga", "title": "Cielos Abiertos", "creator": "Aurora Libre",
                     "licenseurl": "https://creativecommons.org/licenses/by/4.0/"},
        "files": [{"name": "larga.flac", "format": "Flac", "title": "Pieza Larga", "artist": "Aurora Libre",
                   "length": "1500.0", "size": str(len(data)), "md5": hashlib.md5(data).hexdigest(), "_audio": "long"}],
    }
    s = Settings(spotify_client_id="cid", spotify_client_secret="secret", jamendo_client_id="jam",
                 tmp_dir=d / "jobs", cors_origins=(a.cors,), jobs_per_minute=100)
    print(f"E2E backend (simulated external services) on :{a.port}", flush=True)
    uvicorn.run(create_app(s, transport=fake.transport()), host="127.0.0.1", port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
