"""Development/demo server: generated sample audio + an offline fake Spotify.

    python backend/tests/demo_server.py --port 8799 --data-dir /tmp/swc-demo

Prints the media folder to import. Used by the end-to-end UI test (e2e/ui.e2e.js).
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from fake_spotify import CLIENT_ID, FakeSpotify  # noqa: E402


def build_media(d: Path) -> None:
    from conftest import make_tone
    if d.exists():
        shutil.rmtree(d)
    make_tone(d / "Sine Wave Orchestra - La Primera Onda.mp3", 30, 440, ["-c:a", "libmp3lame", "-b:a", "192k"],
              {"title": "La Primera Onda", "artist": "Sine Wave Orchestra", "album": "Tonos de Prueba",
               "genre": "Electronic", "date": "2024", "track": "1"})
    make_tone(d / "album" / "02 Segundo.flac", 40, 660, ["-c:a", "flac"],
              {"title": "Segundo Armónico", "artist": "Sine Wave Orchestra", "album": "Tonos de Prueba",
               "genre": "Electronic", "track": "2"}, rate=96000)
    make_tone(d / "album" / "estatica.ogg", 20, 0, ["-c:a", "libvorbis"],
              {"title": "Estática Nocturna", "artist": "Los Generadores", "album": "Ruido Blanco", "genre": "Noise"},
              source="anoisesrc=d=20:c=pink:r=48000:a=0.3")
    make_tone(d / "otros" / "tono.m4a", 25, 880, ["-c:a", "aac", "-b:a", "128k"],
              {"title": "Tono AAC", "artist": "Codec Lab", "album": "Contenedores", "genre": "Test"})
    make_tone(d / "otros" / "Codec Lab - Crudo.aac", 15, 330, ["-c:a", "aac", "-f", "adts"])
    make_tone(d / "otros" / "mono.wav", 12, 220, ["-c:a", "pcm_s16le"], {"title": "Onda Mono", "artist": "Codec Lab"},
              channels=1)
    make_tone(d / "largo" / "Paciencia - Largo.flac", 900, 440, ["-c:a", "flac"],
              {"title": "Largo", "artist": "Paciencia", "album": "Esperas", "genre": "Drone"})
    (d / "copias").mkdir()
    shutil.copy(d / "Sine Wave Orchestra - La Primera Onda.mp3", d / "copias" / "copia.mp3")
    (d / "otros" / "roto.mp3").write_bytes(os.urandom(4096))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8799)
    ap.add_argument("--data-dir", required=True)
    args = ap.parse_args()
    data = Path(args.data_dir)
    if data.exists():
        shutil.rmtree(data)
    media = data.parent / (data.name + "-media")
    build_media(media)
    fake = FakeSpotify().start()
    os.environ["SWC_SPOTIFY_ACCOUNTS_URL"] = fake.base
    os.environ["SWC_SPOTIFY_API_URL"] = fake.base + "/v1"
    print(f"MEDIA {media}", flush=True)
    print(f"CLIENT_ID {CLIENT_ID}", flush=True)
    from swc.__main__ import main as run
    run(["--port", str(args.port), "--data-dir", str(data)])


if __name__ == "__main__":
    main()
