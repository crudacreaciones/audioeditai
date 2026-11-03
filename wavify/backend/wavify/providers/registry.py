"""Central registry: loads providers from configuration and tracks their real health.

Adding a provider = a new module implementing AudioProvider + its "module:Class" path in WAVIFY_PROVIDERS.
The core never needs to change.
"""
from __future__ import annotations

import importlib
import logging
import time
from collections import deque
from dataclasses import asdict

import httpx

from .base import AudioProvider, ProviderError

log = logging.getLogger("wavify.providers")


class ProviderState:
    def __init__(self, provider: AudioProvider, enabled: bool):
        self.provider = provider
        self.enabled = enabled
        self.verified = False          # True only after a successful real API call
        self.last_check: float | None = None
        self.last_ok: float | None = None
        self.errors: deque = deque(maxlen=20)
        self.consecutive_failures = 0
        self.cooldown_until = 0.0

    @property
    def status(self) -> str:
        if not self.enabled:
            return "disabled"
        if not self.provider.configured():
            return "not_configured"
        if self.cooldown_until > time.time():
            return "down"
        if self.consecutive_failures:
            return "degraded"
        return "ok" if self.verified else "unverified"

    def to_dict(self) -> dict:
        p = self.provider
        return {
            "id": p.id, "name": p.name, "enabled": self.enabled, "configured": p.configured(),
            "missing_configuration": p.missing_configuration(), "status": self.status, "verified": self.verified,
            "capabilities": asdict(p.get_capabilities()), "last_check": self.last_check, "last_ok": self.last_ok,
            "errors": list(self.errors),
        }


class ProviderRegistry:
    def __init__(self, settings, http: httpx.AsyncClient):
        self.settings = settings
        self.http = http
        self.states: dict[str, ProviderState] = {}

    def load_from_settings(self) -> None:
        for path in self.settings.providers:
            module, _, cls_name = path.partition(":")
            try:
                cls = getattr(importlib.import_module(module), cls_name)
            except (ImportError, AttributeError) as e:
                log.error("No se pudo cargar el proveedor %s: %s", path, e)
                continue
            self.register(cls(self.http, self.settings))

    def register(self, provider: AudioProvider) -> None:
        if not provider.id or provider.id in self.states:
            raise ValueError(f"Identificador de proveedor inválido o duplicado: {provider.id!r}")
        enabled = provider.id not in self.settings.disabled_providers
        self.states[provider.id] = ProviderState(provider, enabled)

    def get(self, pid: str) -> ProviderState | None:
        return self.states.get(pid)

    def set_enabled(self, pid: str, enabled: bool) -> bool:
        st = self.states.get(pid)
        if not st:
            return False
        st.enabled = enabled
        return True

    def active(self) -> list[AudioProvider]:
        """Providers that can be queried right now (enabled, configured, not cooling down)."""
        return [s.provider for s in self.states.values() if s.status in ("ok", "unverified", "degraded")]

    def record_success(self, pid: str) -> None:
        st = self.states[pid]
        st.verified, st.consecutive_failures, st.cooldown_until = True, 0, 0.0
        st.last_ok = st.last_check = time.time()

    def record_failure(self, pid: str, error: str) -> None:
        st = self.states[pid]
        st.last_check = time.time()
        st.consecutive_failures += 1
        st.errors.append({"ts": st.last_check, "error": error})
        if st.consecutive_failures >= self.settings.provider_failure_threshold:
            st.cooldown_until = time.time() + self.settings.provider_cooldown
            log.warning("Proveedor %s marcado como no disponible durante %ss", pid, self.settings.provider_cooldown)

    async def check_all(self) -> list[dict]:
        for st in self.states.values():
            if not st.enabled or not st.provider.configured():
                continue
            try:
                await st.provider.health_check()
                self.record_success(st.provider.id)
            except ProviderError as e:
                self.record_failure(st.provider.id, str(e))
            except Exception as e:  # unexpected adapter bug must not take the server down
                self.record_failure(st.provider.id, f"{type(e).__name__}: {e}")
        return [s.to_dict() for s in self.states.values()]

    def summary(self) -> list[dict]:
        return [s.to_dict() for s in self.states.values()]
