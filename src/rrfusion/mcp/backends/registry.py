"""Lane-to-backend registry."""

from __future__ import annotations

from typing import Iterable

from ...config import Settings
from .base import LaneBackend
from .patentfield import PatentfieldBackend
from .wwrag import WWRagBackend


class LaneBackendRegistry:
    """Resolve lane names to their configured adapters."""

    def __init__(self, settings: Settings, overrides: dict[str, LaneBackend] | None = None) -> None:
        self.settings = settings
        default_backends = self._default_backends()
        if overrides:
            default_backends.update(overrides)
        self._backends: dict[str, LaneBackend] = default_backends

    def _default_backends(self) -> dict[str, LaneBackend]:
        pf = PatentfieldBackend(self.settings)
        return {
            "fulltext": pf,
            "semantic": pf,
            "original_dense": WWRagBackend(self.settings),
        }

    def get_backend(self, lane: str) -> LaneBackend | None:
        return self._backends.get(lane)

    def register_backend(self, lane: str, backend: LaneBackend) -> None:
        self._backends[lane] = backend

    def lanes(self) -> Iterable[str]:
        return tuple(self._backends.keys())

    async def close(self) -> None:
        seen_ids: set[int] = set()
        for backend in self._backends.values():
            backend_id = id(backend)
            if backend_id in seen_ids:
                continue
            seen_ids.add(backend_id)
            await backend.close()
