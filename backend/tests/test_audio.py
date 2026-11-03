import itertools
import os
import threading

import pytest

from swc.services.audio import AudioError, ConversionCancelled, FFmpeg, WavSpec
from swc.services.metadata import guess_from_filename, read_tags, write_tags

FF = FFmpeg()
FORMATS = ["Sine Wave Orchestra - La Primera Onda.mp3", "album/02 Segundo.flac", "album/estatica.ogg",
           "otros/tono.m4a", "otros/Codec Lab - Crudo.aac", "otros/mono.wav"]


def test_ffmpeg_available():
    info = FF.available()
    assert info["ffmpeg"] and info["ffprobe"]


@pytest.mark.parametrize("name", FORMATS)
def test_probe_all_formats(media_dir, name):
    info = FF.probe(media_dir / name)
    assert info["duration"] > 1
    assert info["sample_rate"] > 0 and info["channels"] in (1, 2)


def test_probe_corrupt_file(media_dir):
    with pytest.raises(AudioError):
        FF.probe(media_dir / "otros" / "roto.mp3")


@pytest.mark.parametrize("sr,depth,ch", list(itertools.product([44100, 48000, 88200, 96000, 192000],
                                                               ["16", "24", "32f"], [1, 2])))
def test_convert_every_option(media_dir, tmp_path, sr, depth, ch):
    src = media_dir / "album" / "02 Segundo.flac"
    dst = tmp_path / f"out_{sr}_{depth}_{ch}.wav"
    spec = WavSpec(sr, depth, ch)
    progress = []
    FF.convert(src, dst, spec, on_progress=progress.append)
    assert progress and progress[-1] == 1.0
    report = FF.verify_wav(dst, spec, FF.probe(src)["duration"])
    assert report["ok"], report
    info = FF.probe(dst)
    assert info["sample_rate"] == sr and info["channels"] == ch
    assert info["codec"] == {"16": "pcm_s16le", "24": "pcm_s24le", "32f": "pcm_f32le"}[depth]
    assert not os.path.exists(str(dst) + ".part")


@pytest.mark.parametrize("name", FORMATS)
def test_convert_each_input_format(media_dir, tmp_path, name):
    spec = WavSpec(48000, "24", 2)
    dst = tmp_path / "x.wav"
    FF.convert(media_dir / name, dst, spec)
    assert FF.verify_wav(dst, spec, FF.probe(media_dir / name)["duration"])["ok"]


def test_invalid_spec():
    with pytest.raises(AudioError):
        WavSpec(22050, "16", 2).validate()
    with pytest.raises(AudioError):
        WavSpec(44100, "8", 2).validate()
    with pytest.raises(AudioError):
        WavSpec(44100, "16", 6).validate()


def test_cancel_midway(long_flac, tmp_path):
    dst = tmp_path / "cancel.wav"
    ev = threading.Event()

    def on_progress(p):
        if p > 0.02:
            ev.set()

    with pytest.raises(ConversionCancelled):
        FF.convert(long_flac, dst, WavSpec(192000, "32f", 2), on_progress=on_progress, cancel_event=ev)
    assert not dst.exists() and not os.path.exists(str(dst) + ".part")


def test_verify_detects_corruption(media_dir, tmp_path):
    spec = WavSpec(44100, "16", 2)
    dst = tmp_path / "v.wav"
    FF.convert(media_dir / "album" / "02 Segundo.flac", dst, spec)
    # wrong expectations are reported
    assert not FF.verify_wav(dst, WavSpec(48000, "24", 1))["ok"]
    # truncated file fails the duration check
    data = dst.read_bytes()
    dst.write_bytes(data[: len(data) // 2])
    assert not FF.verify_wav(dst, spec, 4.0)["ok"]


def test_tags_read_write(media_dir, tmp_path):
    for name in ("Sine Wave Orchestra - La Primera Onda.mp3", "album/02 Segundo.flac", "album/estatica.ogg",
                 "otros/tono.m4a", "otros/mono.wav"):
        src = media_dir / name
        copy = tmp_path / src.name
        copy.write_bytes(src.read_bytes())
        write_tags(copy, {"title": "Nuevo Título", "artist": "Nuevo Artista", "genre": "Jazz", "year": "1999"})
        tags = read_tags(copy, FF.probe(copy)["tags"])
        assert tags["title"] == "Nuevo Título", name
        assert tags["artist"] == "Nuevo Artista", name
        assert tags["genre"] == "Jazz", name


def test_filename_guess():
    assert guess_from_filename("/x/03 - Artista - Canción.mp3") == {"track_no": "03", "artist": "Artista",
                                                                    "title": "Canción"}
    assert guess_from_filename("solo.flac") == {"title": "solo"}
