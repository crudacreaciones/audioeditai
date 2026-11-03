"""Parallel multi-provider search with timeouts, retries, caching and in-flight de-duplication."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from .matching import normalize
from .providers.base import AudioProvider, Candidate, ProviderError, TrackQuery
from .providers.registry import ProviderRegistry

log = logging.getLogger("wavify.search")


@dataclass
class ProviderResult:
    provider: str
    name: str
    ok: bool
    candidates: list[Candidate] = field(default_factory=list)
    error: str = ""
    elapsed: float = 0.0
    cached: bool = False


class SearchCoordinator:
    def __init__(self, registry: ProviderRegistry, settings):
        self.registry = registry
        self.settings = settings
        self._cache: dict[tuple, tuple[float, list[Candidate]]] = {}
        self._inflight: dict[tuple, asyncio.Future] = {}

    @staticmethod
    def _key(pid: str, q: TrackQuery) -> tuple:
        return (pid, normalize(q.title), normalize(q.main_artist), q.isrc.upper())

    async def search_all(self, query: TrackQuery) -> list[ProviderResult]:
        providers = self.registry.active()
        results = await asyncio.gather(*(self._search_one(p, query) for p in providers))
        for r in results:
            log.info("search provider=%s ok=%s candidates=%d elapsed=%.2fs cached=%s error=%s",
                     r.provider, r.ok, len(r.candidates), r.elapsed, r.cached, r.error)
        return list(results)

    async def _search_one(self, provider: AudioProvider, query: TrackQuery) -> ProviderResult:
        key = self._key(provider.id, query)
        hit = self._cache.get(key)
        if hit and hit[0] > time.time():
            return ProviderResult(provider.id, provider.name, True, list(hit[1]), cached=True)
        if key in self._inflight:  # identical query already running: share its result
            try:
                cands = await asyncio.shield(self._inflight[key])
                return ProviderResult(provider.id, provider.name, True, list(cands), cached=True)
            except Exception as e:
                return ProviderResult(provider.id, provider.name, False, error=str(e))
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._inflight[key] = fut
        start = time.monotonic()
        try:
            cands = await self._with_retries(provider, query)
            self._cache[key] = (time.time() + self.settings.cache_ttl, cands)
            self.registry.record_success(provider.id)
            fut.set_result(cands)
            return ProviderResult(provider.id, provider.name, True, list(cands), elapsed=time.monotonic() - start)
        except asyncio.CancelledError:
            fut.cancel()
            raise
        except Exception as e:  # one provider failing never stops the others
            msg = str(e) or type(e).__name__
            if not isinstance(e, (ProviderError, asyncio.TimeoutError)):
                msg = f"Error interno del adaptador: {type(e).__name__}: {e}"
            self.registry.record_failure(provider.id, msg)
            fut.set_exception(e)
            fut.exception()  # mark retrieved
            return ProviderResult(provider.id, provider.name, False, error=msg, elapsed=time.monotonic() - start)
        finally:
            self._inflight.pop(key, None)

    async def _with_retries(self, provider: AudioProvider, query: TrackQuery) -> list[Candidate]:
        attempts = 1 + max(0, self.settings.provider_retries)
        for i in range(attempts):
            try:
                return await asyncio.wait_for(provider.search(query), timeout=self.settings.provider_timeout)
            except asyncio.TimeoutError:
                err: Exception = ProviderError(f"{provider.name}: tiempo de espera agotado", transient=True)
            except ProviderError as e:
                err = e
            if not getattr(err, "transient", False) or i == attempts - 1:
                raise err
            await asyncio.sleep(0.5 * (2 ** i))
        raise AssertionError("unreachable")

    def clear_cache(self) -> None:
        self._cache.clear()
