# Module name: connections/sdr/backend.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


"""SDRBackend — one helper per device family over its host library.

The connection and the driver are shared by every family; what differs between
host libraries lives here (HLRQ-16 §4a, BR-13). A backend is a helper, not a
primitive: nothing in the ontology is its base, and only the connection reaches
it (NFRQ-ORG-04).
"""

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from abc import ABC, abstractmethod
from collections.abc import Mapping
from importlib import import_module, metadata
from typing import Any, ClassVar
from .errors import SDRBackendUnavailable
from .profile import SDREffective, SDRInstance, SDRReported
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = ["SDRBackend"]


class SDRBackend(ABC):
    FAMILY: ClassVar[str] = ""
    # Distribution whose version a profile's `requires` is compared with.
    DISTRIBUTION: ClassVar[str | None] = None
    # Byte multiple a single read must respect (USB transfer granularity).
    BLOCK_ALIGN: ClassVar[int] = 1
    # Whether the host library reports dropped samples at all.
    MEASURES_LOSS: ClassVar[bool] = False
    # Families shipped here, imported on first use so no host library loads early.
    BUILTIN: ClassVar[dict[str, str]] = {"rtlsdr": "wattleflow.connections.sdr.rtl"}
    _registry: ClassVar[dict[str, type[SDRBackend]]] = {}

    def __init__(self, owner: Any) -> None:
        # The owning connection is the caller named in every failure raised here.
        self._owner = owner

    @classmethod
    def register(cls, backend: type[SDRBackend]) -> None:
        cls._registry[backend.FAMILY] = backend

    @classmethod
    def for_family(cls, family: str, owner: Any) -> SDRBackend:
        if family not in cls._registry and family in cls.BUILTIN:
            import_module(cls.BUILTIN[family])
        backend = cls._registry.get(family)
        if backend is None:
            known = sorted(set(cls._registry) | set(cls.BUILTIN))
            raise SDRBackendUnavailable(
                caller=owner, error=f"no backend for family {family!r}; known: {known}"
            )
        return backend(owner)

    def debug(self, **fields: Any) -> None:
        """A trace through the owning connection; the backend keeps no logger of its own."""
        self._owner.debug(**fields)

    def version(self) -> str | None:
        if not self.DISTRIBUTION:
            return None
        try:
            return metadata.version(self.DISTRIBUTION)
        except metadata.PackageNotFoundError:
            return None

    @abstractmethod
    def enumerate(self) -> list[dict[str, str]]:
        """Every attached unit, as string keys a selector can match."""

    @abstractmethod
    def claim(self, device: Mapping[str, str]) -> Any:
        """Open the unit exclusively; busy, rights and reachability fail by type."""

    @abstractmethod
    def report(self, session: Any) -> SDRReported: ...

    @abstractmethod
    def supports(self, model: Mapping[str, str]) -> bool: ...

    @abstractmethod
    def apply(self, session: Any, instance: SDRInstance) -> None: ...

    @abstractmethod
    def read_back(self, session: Any) -> SDREffective: ...

    @abstractmethod
    def tune(self, session: Any, hz: float) -> None: ...

    @abstractmethod
    def read(self, session: Any, nbytes: int) -> bytes: ...

    @abstractmethod
    def release(self, session: Any) -> None: ...
