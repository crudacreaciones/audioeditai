"""MP3 conversion with FFmpeg: honest bitrate decisions, progress, cancellation and verification."""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .config import MP3_BITRATES

FFMPEG = os.environ.get("WAVIFY_FFMPEG") or shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = os.environ.get("WAVIFY_FFPROBE") or shutil.which("ffprobe") or "ffprobe"
LOSSLESS = {"flac", "alac", "wavpack", "ape", "tta"}


class ConversionError(Exception):
    pass


@dataclass
class SourceInfo:
    codec: str
    bitrate_kbps: int | None
    sample_rate: int
    channels: int
    duration: float

    @property
    def lossless(self) -> bool:
        return self.codec in LOSSLESS or self.codec.startswith("pcm_")


@dataclass
class Plan:
    mode: str               # "encode" | "copy"
    bitrate_kbps: int       # actual bitrate of the output
    note: str = ""


async def _run(*args: str, timeout: float = 120) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        proc.kill()
        await proc.wait()
        raise
    return proc.returncode, out.decode(errors="replace"), err.decode(errors="replace")


async def probe(path: Path) -> SourceInfo:
    if not path.exists() or path.stat().st_size == 0:
        raise ConversionError("El archivo de audio está vacío.")
    code, out, err = await _run(FFPROBE, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path))
    if code != 0:
        raise ConversionError("El archivo de audio está dañado o no es un formato de audio válido.")
    data = json.loads(out or "{}")
    a = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    if not a:
        raise ConversionError("El archivo no contiene audio.")
    fmt = data.get("format", {})
    br = a.get("bit_rate") or fmt.get("bit_rate")
    dur = float(a.get("duration") or fmt.get("duration") or 0)
    if dur <= 0:
        raise ConversionError("El archivo de audio está dañado (no tiene una duración válida).")
    return SourceInfo(codec=a.get("codec_name", ""), bitrate_kbps=round(int(br) / 1000) if br else None,
                      sample_rate=int(a.get("sample_rate") or 0), channels=int(a.get("channels") or 0), duration=dur)


def plan(src: SourceInfo, requested: int) -> Plan:
    """Never claim a quality the source does not have."""
    if requested not in MP3_BITRATES:
        raise ConversionError("Calidad MP3 no soportada.")
    if src.lossless:
        return Plan("encode", requested)
    sb = src.bitrate_kbps or 0
    if src.codec == "mp3" and sb and sb <= requested + 8:
        return Plan("copy", sb, f"El original ya es MP3 a {sb} kbps: se conserva sin recodificar. "
                                f"Convertirlo a {requested} kbps no mejoraría la calidad.")
    if sb and sb < requested:
        eff = next((b for b in MP3_BITRATES if b >= sb), MP3_BITRATES[-1])
        return Plan("encode", eff, f"El original tiene {sb} kbps: se genera a {eff} kbps porque una tasa mayor "
                                   f"no mejoraría la calidad.")
    return Plan("encode", requested)


def _meta_args(tags: dict) -> list[str]:
    args = []
    for k in ("title", "artist", "album", "date", "comment", "copyright"):
        if tags.get(k):
            args += ["-metadata", f"{k}={tags[k]}"]
    return args


async def to_mp3(src: Path, dst: Path, requested_kbps: int, tags: dict,
                 on_progress: Callable[[float], None] | None = None) -> dict:
    info = await probe(src)
    p = plan(info, requested_kbps)
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(".part.mp3")
    cmd = [FFMPEG, "-hide_banner", "-nostdin", "-y", "-v", "error", "-i", str(src), "-map", "0:a:0", "-vn",
           "-map_metadata", "-1"]
    if p.mode == "copy":
        cmd += ["-c:a", "copy"]
    else:
        cmd += ["-c:a", "libmp3lame", "-b:a", f"{p.bitrate_kbps}k"]
        if info.sample_rate > 48000:
            cmd += ["-ar", "48000"]  # MP3 does not support > 48 kHz
        if info.channels > 2:
            cmd += ["-ac", "2"]
    cmd += ["-id3v2_version", "3", *_meta_args(tags), "-progress", "pipe:1", "-nostats", "-f", "mp3", str(tmp)]
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        assert proc.stdout is not None
        async for raw in proc.stdout:
            key, _, val = raw.decode(errors="replace").strip().partition("=")
            if key == "out_time_us" and on_progress and val.isdigit():
                on_progress(min(0.99, int(val) / 1e6 / info.duration))
        err = (await proc.stderr.read()).decode(errors="replace") if proc.stderr else ""
        rc = await proc.wait()
        if rc != 0:
            raise ConversionError("No se pudo convertir el audio: " + (err.strip()[-200:] or f"código {rc}"))
        await verify(tmp, info.duration)
        os.replace(tmp, dst)
    except asyncio.CancelledError:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        raise
    finally:
        tmp.unlink(missing_ok=True)
    if on_progress:
        on_progress(1.0)
    return {"bitrate_kbps": p.bitrate_kbps, "mode": p.mode, "note": p.note, "size": dst.stat().st_size,
            "duration": info.duration, "source_codec": info.codec, "source_bitrate_kbps": info.bitrate_kbps,
            "source_lossless": info.lossless}


async def verify(path: Path, expected_duration: float) -> None:
    out = await probe(path)
    if out.codec != "mp3":
        raise ConversionError("El archivo generado no es MP3.")
    if abs(out.duration - expected_duration) > max(0.5, expected_duration * 0.01):
        raise ConversionError("El MP3 generado no tiene la duración esperada.")
    code, _, err = await _run(FFMPEG, "-v", "error", "-xerror", "-i", str(path), "-f", "null", "-", timeout=600)
    if code != 0 or err.strip():
        raise ConversionError("El MP3 generado contiene errores.")


def clean_filename(artist: str, title: str) -> str:
    name = f"{artist} - {title}" if artist else title
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name)
    name = re.sub(r"\s+", " ", name).strip().strip(".")
    return (name[:120] or "wavify") + ".mp3"
