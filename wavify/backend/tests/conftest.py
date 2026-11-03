import asyncio
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from wavify.config import Settings  # noqa: E402


def _gen(path: Path, args: list[str], src: str = "sine=frequency=440:sample_rate=44100:duration=6") -> bytes:
    subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i", src, "-ac", "2", *args, str(path)],
                   check=True)
    return path.read_bytes()


@pytest.fixture(scope="session")
def audio(tmp_path_factory) -> dict[str, bytes]:
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg required")
    d = tmp_path_factory.mktemp("audio")
    a = {
        "flac6": _gen(d / "a.flac", ["-c:a", "flac"]),
        "flac96k": _gen(d / "b.flac", ["-c:a", "flac"], "sine=frequency=440:sample_rate=96000:duration=6"),
        "mp3_128": _gen(d / "c.mp3", ["-c:a", "libmp3lame", "-b:a", "128k"]),
        "mp3_320": _gen(d / "d.mp3", ["-c:a", "libmp3lame", "-b:a", "320k"]),
        "ogg_96": _gen(d / "e.ogg", ["-c:a", "libvorbis", "-b:a", "96k"]),
        "long_flac": _gen(d / "f.flac", ["-c:a", "flac"], "sine=frequency=440:sample_rate=44100:duration=900"),
    }
    a["corrupt"] = b"\x00\x01garbage" * 500
    a["empty"] = b""
    return a


@pytest.fixture()
def settings(tmp_path) -> Settings:
    return Settings(spotify_client_id="cid", spotify_client_secret="secret", jamendo_client_id="jam",
                    tmp_dir=tmp_path / "tmp", provider_timeout=5, jobs_per_minute=100)


def run(coro):
    return asyncio.run(coro)
