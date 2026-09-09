# Module name: metrics/__init__.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# Lazy public API (PEP 562) — DR-WFL-007.
#
# A sink names a driver, and a driver names a third-party client. Eager
# re-exports would make importing the package require `requests` even for a
# deployment that publishes nowhere. Collection itself lives in
# `wattleflow.helpers.metrics` and needs none of this.
# --------------------------------------------------------------------------- #

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS: dict[str, str] = {
    "GrafanaSink": "sinks",
    "PrometheusSink": "sinks",
    "SinkError": "sinks",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(import_module(f".{module}", __name__), name)


def __dir__() -> list[str]:
    return sorted(__all__)
