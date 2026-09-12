# Module name: connections/sdr/__init__.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# Lazy public API (PEP 562) — DR-WFL-007. No name here loads a host library:
# the family backend imports its library on first use.
# --------------------------------------------------------------------------- #

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS: dict[str, str] = {
    "Direction": "profile",
    "Duplex": "profile",
    "SampleFormat": "profile",
    "SDREffective": "profile",
    "SDRInstance": "profile",
    "SDRProfile": "profile",
    "SDRReported": "profile",
    "SDRSelector": "profile",
    "SDRTuningPlan": "profile",
    "SDRBackend": "backend",
    "RTLSDRBackend": "rtl",
    "SDRConnection": "connection",
    "SDRBackendUnavailable": "errors",
    "SDRConfigurationError": "errors",
    "SDRConnectionError": "errors",
    "SDRDeviceAmbiguous": "errors",
    "SDRDeviceBusy": "errors",
    "SDRDeviceNotFound": "errors",
    "SDRFrequencyOutOfRange": "errors",
    "SDRModelUnsupported": "errors",
    "SDRPermissionDenied": "errors",
    "SDRProfileMismatch": "errors",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    """Resolve one public name by importing only its defining submodule."""
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(import_module(f".{module}", __name__), name)


def __dir__() -> list[str]:
    return sorted(__all__)
