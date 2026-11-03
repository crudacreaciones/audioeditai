import asyncio
import subprocess

import pytest

from conftest import run
from wavify import converter


def write(tmp_path, audio, key, ext):
    p = tmp_path / f"{key}.{ext}"
    p.write_bytes(audio[key])
    return p


def ffprobe(path):
    import json
    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
                         capture_output=True, text=True, check=True).stdout
    d = json.loads(out)
    return d["streams"][0], d["format"]


@pytest.mark.parametrize("kbps", [128, 192, 256, 320])
def test_lossless_to_each_bitrate(audio, tmp_path, kbps):
    src = write(tmp_path, audio, "flac6", "flac")
    progress = []
    res = run(converter.to_mp3(src, tmp_path / "o.mp3", kbps, {"title": "Luz de Mañana", "artist": "Aurora Libre",
                                                                "album": "Cielos", "comment": "Licencia: CC BY"},
                               progress.append))
    s, f = ffprobe(tmp_path / "o.mp3")
    assert s["codec_name"] == "mp3" and abs(int(f["bit_rate"]) / 1000 - kbps) < kbps * 0.05
    assert res["bitrate_kbps"] == kbps and res["mode"] == "encode" and not res["note"]
    assert f["tags"]["title"] == "Luz de Mañana" and f["tags"]["artist"] == "Aurora Libre"
    assert progress[-1] == 1.0
    assert not (tmp_path / "o.part.mp3").exists()


def test_never_upsamples_bitrate(audio, tmp_path):
    # MP3 128 kbps source, 320 requested -> kept at 128 without re-encoding, and the user is told why
    res = run(converter.to_mp3(write(tmp_path, audio, "mp3_128", "mp3"), tmp_path / "a.mp3", 320, {}))
    assert res["mode"] == "copy" and res["bitrate_kbps"] == 128 and "no mejoraría" in res["note"]
    # Ogg ~96 kbps source, 320 requested -> 128 (smallest standard >= source)
    res = run(converter.to_mp3(write(tmp_path, audio, "ogg_96", "ogg"), tmp_path / "b.mp3", 320, {}))
    assert res["mode"] == "encode" and res["bitrate_kbps"] == 128 and "no mejoraría" in res["note"]
    # MP3 320 source, 128 requested -> re-encoded down as asked
    res = run(converter.to_mp3(write(tmp_path, audio, "mp3_320", "mp3"), tmp_path / "c.mp3", 128, {}))
    assert res["mode"] == "encode" and res["bitrate_kbps"] == 128


def test_high_sample_rate_source(audio, tmp_path):
    run(converter.to_mp3(write(tmp_path, audio, "flac96k", "flac"), tmp_path / "o.mp3", 320, {}))
    s, _ = ffprobe(tmp_path / "o.mp3")
    assert s["sample_rate"] == "48000"


@pytest.mark.parametrize("key,msg", [("corrupt", "dañado"), ("empty", "vacío")])
def test_corrupt_and_empty(audio, tmp_path, key, msg):
    with pytest.raises(converter.ConversionError, match=msg):
        run(converter.to_mp3(write(tmp_path, audio, key, "flac"), tmp_path / "o.mp3", 320, {}))
    assert not (tmp_path / "o.mp3").exists()


def test_invalid_bitrate(audio, tmp_path):
    with pytest.raises(converter.ConversionError):
        run(converter.to_mp3(write(tmp_path, audio, "flac6", "flac"), tmp_path / "o.mp3", 999, {}))


def test_cancellation_kills_ffmpeg_and_cleans_up(audio, tmp_path):
    src = write(tmp_path, audio, "long_flac", "flac")

    async def go():
        seen = asyncio.Event()
        task = asyncio.create_task(converter.to_mp3(src, tmp_path / "o.mp3", 320, {},
                                                    lambda p: seen.set() if p > 0.01 else None))
        await asyncio.wait_for(seen.wait(), 30)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    run(go())
    assert not (tmp_path / "o.mp3").exists() and not (tmp_path / "o.part.mp3").exists()
    out = subprocess.run(["pgrep", "-f", str(tmp_path / "o.part.mp3")], capture_output=True)
    assert out.returncode == 1, "ffmpeg process left running"


def test_clean_filename():
    assert converter.clean_filename("AC/DC", 'Back: In "Black"?') == "ACDC - Back In Black.mp3"
    assert converter.clean_filename("", "  ...  ") == "wavify.mp3"
