import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_spotify import CLIENT_ID, FakeSpotify  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg required")


def make_tone(path: Path, seconds: float, freq: int = 440, codec_args=(), tags: dict | None = None,
              rate: int = 44100, channels: int = 2, source: str | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    src = source or f"sine=frequency={freq}:sample_rate={rate}:duration={seconds}"
    cmd = ["ffmpeg", "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i", src, "-ac", str(channels)]
    for k, v in (tags or {}).items():
        cmd += ["-metadata", f"{k}={v}"]
    cmd += list(codec_args) + [str(path)]
    subprocess.run(cmd, check=True)
    return path


@pytest.fixture(scope="session")
def media_dir(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("media")
    make_tone(d / "Sine Wave Orchestra - La Primera Onda.mp3", 3, 440, ["-c:a", "libmp3lame", "-b:a", "192k"],
              {"title": "La Primera Onda", "artist": "Sine Wave Orchestra", "album": "Tonos de Prueba",
               "genre": "Electronic", "date": "2024", "track": "1"})
    make_tone(d / "album" / "02 Segundo.flac", 4, 660, ["-c:a", "flac"],
              {"title": "Segundo Armónico", "artist": "Sine Wave Orchestra", "album": "Tonos de Prueba",
               "genre": "Electronic", "track": "2"}, rate=96000)
    make_tone(d / "album" / "estatica.ogg", 2, 0, ["-c:a", "libvorbis"],
              {"title": "Estática Nocturna", "artist": "Los Generadores", "album": "Ruido Blanco", "genre": "Noise"},
              source="anoisesrc=d=2:c=pink:r=48000:a=0.3")
    make_tone(d / "otros" / "tono.m4a", 2.5, 880, ["-c:a", "aac", "-b:a", "128k"],
              {"title": "Tono AAC", "artist": "Codec Lab", "album": "Contenedores", "genre": "Test"})
    make_tone(d / "otros" / "Codec Lab - Crudo.aac", 1.5, 330, ["-c:a", "aac", "-f", "adts"])
    make_tone(d / "otros" / "mono.wav", 2, 220, ["-c:a", "pcm_s16le"],
              {"title": "Onda Mono", "artist": "Codec Lab"}, channels=1)
    # exact duplicate of the mp3 inside a sub-folder
    (d / "copias").mkdir()
    shutil.copy(d / "Sine Wave Orchestra - La Primera Onda.mp3", d / "copias" / "copia.mp3")
    # corrupt "audio" file + non-audio file (ignored)
    (d / "otros" / "roto.mp3").write_bytes(os.urandom(2048))
    (d / "otros" / "notas.txt").write_text("not audio")
    return d


@pytest.fixture(scope="session")
def long_flac(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("long")
    return make_tone(d / "largo.flac", 600, 440, ["-c:a", "flac"], {"title": "Largo", "artist": "Paciencia"})


@pytest.fixture()
def fake_spotify():
    fs = FakeSpotify().start()
    yield fs
    fs.stop()


@pytest.fixture()
def client(tmp_path, fake_spotify, monkeypatch):
    from fastapi.testclient import TestClient
    from swc.app import create_app
    from swc.config import load_config

    monkeypatch.setenv("SWC_SPOTIFY_ACCOUNTS_URL", fake_spotify.base)
    monkeypatch.setenv("SWC_SPOTIFY_API_URL", fake_spotify.base + "/v1")
    cfg = load_config(tmp_path / "data")
    app = create_app(cfg)
    with TestClient(app, headers={"X-SWC": "1"}) as c:
        c.fake = fake_spotify
        c.svc = app.state.svc
        c.client_id = CLIENT_ID
        yield c


def wait_for(fn, timeout=60, interval=0.1):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(interval)
    raise TimeoutError("condition not met")
