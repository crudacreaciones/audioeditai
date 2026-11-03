"""Application paths and runtime configuration."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

APP_NAME = "Spotify to WAV Converter"
APP_VERSION = "1.0.0"

AUDIO_EXTENSIONS = {".mp3", ".flac", ".m4a", ".aac", ".ogg", ".oga", ".wav"}

SAMPLE_RATES = [44100, 48000, 88200, 96000, 192000]
BIT_DEPTHS = {
    "16": {"codec": "pcm_s16le", "label": "16 bits"},
    "24": {"codec": "pcm_s24le", "label": "24 bits"},
    "32f": {"codec": "pcm_f32le", "label": "32 bits float"},
}
CHANNEL_OPTIONS = {1: "Mono", 2: "Estéreo"}

DEFAULT_SETTINGS = {
    "spotify_client_id": "",
    "spotify_redirect_uri": "",  # computed from the server port when empty
    "output_dir": "",  # computed from data dir when empty
    "default_sample_rate": 44100,
    "default_bit_depth": "16",
    "default_channels": 2,
    "concurrency": 2,
    "naming_pattern": "{artist} - {title}",
    "verify_after_convert": True,
    "skip_exact_duplicates": True,
}


@dataclass
class AppConfig:
    data_dir: Path
    host: str = "127.0.0.1"
    port: int = 8765
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    spotify_accounts_url: str = "https://accounts.spotify.com"
    spotify_api_url: str = "https://api.spotify.com/v1"
    extra: dict = field(default_factory=dict)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "library.db"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def default_output_dir(self) -> Path:
        return self.data_dir / "converted"

    @property
    def default_redirect_uri(self) -> str:
        # Spotify requires an explicit loopback IP literal (not "localhost").
        return f"http://127.0.0.1:{self.port}/api/spotify/callback"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.log_dir, self.default_output_dir):
            d.mkdir(parents=True, exist_ok=True)


def load_config(data_dir: str | os.PathLike | None = None, port: int | None = None) -> AppConfig:
    base = Path(data_dir or os.environ.get("SWC_DATA_DIR") or Path.home() / ".spotify-wav-converter")
    cfg = AppConfig(
        data_dir=base.expanduser().resolve(),
        port=int(port or os.environ.get("SWC_PORT", 8765)),
        ffmpeg=os.environ.get("SWC_FFMPEG", "ffmpeg"),
        ffprobe=os.environ.get("SWC_FFPROBE", "ffprobe"),
        spotify_accounts_url=os.environ.get("SWC_SPOTIFY_ACCOUNTS_URL", "https://accounts.spotify.com").rstrip("/"),
        spotify_api_url=os.environ.get("SWC_SPOTIFY_API_URL", "https://api.spotify.com/v1").rstrip("/"),
    )
    cfg.ensure_dirs()
    return cfg
