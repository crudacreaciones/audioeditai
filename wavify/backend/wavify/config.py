"""Server-side configuration. Secrets live only here (environment variables), never in the mobile client."""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PROVIDERS = (
    "wavify.providers.internet_archive:InternetArchiveProvider",
    "wavify.providers.jamendo:JamendoProvider",
)

MP3_BITRATES = (128, 192, 256, 320)


def _env_list(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.environ.get(name, "").strip()
    return tuple(x.strip() for x in raw.split(",") if x.strip()) if raw else default


@dataclass
class Settings:
    # credentials (server only)
    spotify_client_id: str = ""
    spotify_client_secret: str = ""
    jamendo_client_id: str = ""
    admin_token: str = ""
    # endpoints (overridable for tests)
    spotify_api_url: str = "https://api.spotify.com/v1"
    spotify_accounts_url: str = "https://accounts.spotify.com"
    internet_archive_url: str = "https://archive.org"
    jamendo_api_url: str = "https://api.jamendo.com/v3.0"
    # providers
    providers: tuple[str, ...] = DEFAULT_PROVIDERS
    disabled_providers: tuple[str, ...] = ()
    provider_timeout: float = 15.0
    provider_retries: int = 1
    provider_cooldown: float = 60.0
    provider_failure_threshold: int = 3
    cache_ttl: float = 600.0
    # files
    tmp_dir: Path = field(default_factory=lambda: Path(tempfile.gettempdir()) / "wavify")
    file_ttl: float = 1800.0
    max_download_bytes: int = 300 * 1024 * 1024
    # limits
    jobs_per_minute: int = 10
    max_concurrent_jobs: int = 3
    cors_origins: tuple[str, ...] = ()

    @classmethod
    def from_env(cls) -> "Settings":
        e = os.environ.get
        s = cls(
            spotify_client_id=e("SPOTIFY_CLIENT_ID", ""),
            spotify_client_secret=e("SPOTIFY_CLIENT_SECRET", ""),
            jamendo_client_id=e("JAMENDO_CLIENT_ID", ""),
            admin_token=e("WAVIFY_ADMIN_TOKEN", ""),
            providers=_env_list("WAVIFY_PROVIDERS", DEFAULT_PROVIDERS),
            disabled_providers=_env_list("WAVIFY_DISABLED_PROVIDERS", ()),
            cors_origins=_env_list("WAVIFY_CORS_ORIGINS", ()),
        )
        if e("WAVIFY_TMP_DIR"):
            s.tmp_dir = Path(e("WAVIFY_TMP_DIR"))
        for attr, var, conv in (("file_ttl", "WAVIFY_FILE_TTL", float),
                                ("jobs_per_minute", "WAVIFY_JOBS_PER_MINUTE", int),
                                ("max_concurrent_jobs", "WAVIFY_MAX_CONCURRENT_JOBS", int),
                                ("provider_timeout", "WAVIFY_PROVIDER_TIMEOUT", float)):
            if e(var):
                setattr(s, attr, conv(e(var)))
        return s
