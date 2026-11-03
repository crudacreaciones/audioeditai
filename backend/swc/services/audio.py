"""FFmpeg / FFprobe wrappers: probing, WAV conversion with progress & cancel, integrity checks."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..config import BIT_DEPTHS, SAMPLE_RATES

# Hide console windows for child processes on Windows.
_CREATE_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class AudioError(Exception):
    pass


class ConversionCancelled(Exception):
    pass


def sha256_file(path: str | os.PathLike, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


@dataclass
class WavSpec:
    sample_rate: int = 44100
    bit_depth: str = "16"  # "16" | "24" | "32f"
    channels: int = 2

    def validate(self) -> "WavSpec":
        if int(self.sample_rate) not in SAMPLE_RATES:
            raise AudioError(f"Frecuencia de muestreo no soportada: {self.sample_rate}")
        if str(self.bit_depth) not in BIT_DEPTHS:
            raise AudioError(f"Profundidad de bits no soportada: {self.bit_depth}")
        if int(self.channels) not in (1, 2):
            raise AudioError(f"Canales no soportados: {self.channels}")
        self.sample_rate, self.bit_depth, self.channels = int(self.sample_rate), str(self.bit_depth), int(self.channels)
        return self

    @property
    def codec(self) -> str:
        return BIT_DEPTHS[self.bit_depth]["codec"]


class FFmpeg:
    def __init__(self, ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe"):
        self.ffmpeg = shutil.which(ffmpeg) or ffmpeg
        self.ffprobe = shutil.which(ffprobe) or ffprobe
        self._soxr: bool | None = None

    # ---- environment ----------------------------------------------------
    def available(self) -> dict:
        info = {"ffmpeg": None, "ffprobe": None}
        for key, exe in (("ffmpeg", self.ffmpeg), ("ffprobe", self.ffprobe)):
            try:
                out = subprocess.run([exe, "-version"], capture_output=True, text=True, timeout=10, creationflags=_CREATE_FLAGS)
                if out.returncode == 0:
                    info[key] = out.stdout.splitlines()[0]
            except (OSError, subprocess.SubprocessError):
                pass
        info["soxr"] = self.has_soxr() if info["ffmpeg"] else False
        return info

    def has_soxr(self) -> bool:
        if self._soxr is None:
            try:
                r = subprocess.run(
                    [self.ffmpeg, "-hide_banner", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
                     "-t", "0.05", "-af", "aresample=48000:resampler=soxr", "-f", "null", "-"],
                    capture_output=True, timeout=15, creationflags=_CREATE_FLAGS,
                )
                self._soxr = r.returncode == 0
            except (OSError, subprocess.SubprocessError):
                self._soxr = False
        return self._soxr

    # ---- probing --------------------------------------------------------
    def probe(self, path: str | os.PathLike) -> dict:
        try:
            r = subprocess.run(
                [self.ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                capture_output=True, text=True, timeout=60, creationflags=_CREATE_FLAGS,
            )
        except (OSError, subprocess.SubprocessError) as e:
            raise AudioError(f"No se pudo ejecutar ffprobe: {e}") from e
        if r.returncode != 0:
            raise AudioError(f"Archivo no válido o dañado: {r.stderr.strip()[:300] or 'ffprobe falló'}")
        data = json.loads(r.stdout or "{}")
        audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
        if not audio:
            raise AudioError("El archivo no contiene ninguna pista de audio")
        fmt = data.get("format", {})
        duration = float(audio.get("duration") or fmt.get("duration") or 0)
        bit_depth = int(audio.get("bits_per_raw_sample") or audio.get("bits_per_sample") or 0)
        tags = {k.lower(): v for k, v in (fmt.get("tags") or {}).items()}
        tags.update({k.lower(): v for k, v in (audio.get("tags") or {}).items() if k.lower() not in tags})
        return {
            "format": fmt.get("format_name", ""),
            "codec": audio.get("codec_name", ""),
            "sample_fmt": audio.get("sample_fmt", ""),
            "sample_rate": int(audio.get("sample_rate") or 0),
            "channels": int(audio.get("channels") or 0),
            "bit_depth": bit_depth,
            "bitrate": int(fmt.get("bit_rate") or audio.get("bit_rate") or 0),
            "duration": duration,
            "tags": tags,
        }

    # ---- conversion -----------------------------------------------------
    def build_convert_cmd(self, src: str, dst: str, spec: WavSpec) -> list[str]:
        resampler = "aresample={sr}".format(sr=spec.sample_rate)
        if self.has_soxr():
            resampler += ":resampler=soxr:precision=28"
        if spec.bit_depth == "16":
            resampler += ":dither_method=triangular"
        return [
            self.ffmpeg, "-hide_banner", "-nostdin", "-y", "-v", "error",
            "-i", src,
            "-map", "0:a:0", "-vn", "-sn", "-dn",
            "-map_metadata", "0",
            "-af", resampler,
            "-ar", str(spec.sample_rate),
            "-ac", str(spec.channels),
            "-c:a", spec.codec,
            "-rf64", "auto",
            "-f", "wav",
            "-progress", "pipe:1", "-nostats",
            dst,
        ]

    def convert(
        self,
        src: str | os.PathLike,
        dst: str | os.PathLike,
        spec: WavSpec,
        duration: float | None = None,
        on_progress: Callable[[float], None] | None = None,
        cancel_event: threading.Event | None = None,
        register_process: Callable[[subprocess.Popen], None] | None = None,
    ) -> None:
        """Convert `src` to WAV at `dst`. Writes to a temporary file and renames on success."""
        spec.validate()
        src, dst = str(src), str(dst)
        if not os.path.isfile(src):
            raise AudioError(f"El archivo de origen no existe: {src}")
        if duration is None:
            duration = self.probe(src)["duration"]
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        tmp = dst + ".part"
        cmd = self.build_convert_cmd(src, tmp, spec)
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                    creationflags=_CREATE_FLAGS)
        except OSError as e:
            raise AudioError(f"No se pudo iniciar ffmpeg: {e}") from e
        if register_process:
            register_process(proc)

        stderr_chunks: list[str] = []
        t_err = threading.Thread(target=lambda: stderr_chunks.append(proc.stderr.read()), daemon=True)
        t_err.start()
        try:
            for line in proc.stdout:  # type: ignore[union-attr]
                if cancel_event is not None and cancel_event.is_set():
                    proc.kill()
                    break
                key, _, val = line.strip().partition("=")
                if key in ("out_time_us", "out_time_ms") and duration and on_progress:
                    try:
                        secs = int(val) / 1_000_000
                        on_progress(max(0.0, min(0.999, secs / duration)))
                    except ValueError:
                        pass
            proc.wait()
            t_err.join(timeout=5)
            if cancel_event is not None and cancel_event.is_set():
                raise ConversionCancelled()
            if proc.returncode != 0:
                msg = "".join(stderr_chunks).strip()[-500:] or f"ffmpeg terminó con código {proc.returncode}"
                raise AudioError(msg)
            os.replace(tmp, dst)
            if on_progress:
                on_progress(1.0)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    # ---- verification ---------------------------------------------------
    def verify_wav(self, path: str | os.PathLike, spec: WavSpec, expected_duration: float | None = None) -> dict:
        """Check stream parameters, duration and decode the whole file looking for errors."""
        report: dict = {"ok": False, "checks": []}

        def check(name: str, ok: bool, detail: str = "") -> None:
            report["checks"].append({"name": name, "ok": bool(ok), "detail": detail})

        path = str(path)
        if not os.path.isfile(path) or os.path.getsize(path) <= 44:
            check("archivo", False, "El archivo no existe o está vacío")
            return report
        try:
            info = self.probe(path)
        except AudioError as e:
            check("ffprobe", False, str(e))
            return report
        check("contenedor WAV", "wav" in info["format"], info["format"])
        check("códec", info["codec"] == spec.codec, f"{info['codec']} (esperado {spec.codec})")
        check("frecuencia", info["sample_rate"] == spec.sample_rate, f"{info['sample_rate']} Hz")
        check("canales", info["channels"] == spec.channels, str(info["channels"]))
        if expected_duration:
            diff = abs(info["duration"] - expected_duration)
            tol = max(0.15, expected_duration * 0.005)
            check("duración", diff <= tol, f"{info['duration']:.3f}s vs {expected_duration:.3f}s")
        r = subprocess.run(
            [self.ffmpeg, "-hide_banner", "-nostdin", "-v", "error", "-xerror", "-i", path, "-f", "null", "-"],
            capture_output=True, text=True, timeout=1800, creationflags=_CREATE_FLAGS,
        )
        check("decodificación completa", r.returncode == 0 and not r.stderr.strip(), r.stderr.strip()[:300])
        report["info"] = {k: v for k, v in info.items() if k != "tags"}
        report["ok"] = all(c["ok"] for c in report["checks"])
        return report
