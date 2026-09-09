# Module name: helpers/converters/__init__.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# Lazy public API (PEP 562) — DR-WFL-007.
# --------------------------------------------------------------------------- #

from __future__ import annotations

from importlib import import_module
from typing import Any

# Public name -> defining submodule. Extend this when a member is added; it is
# the single declaration of what this package exposes and from where.
_EXPORTS: dict[str, str] = {
    "PdfConverter": "pdf",
    "PDF_FONT_FAMILY": "pdf",
    "SpanList": "pdf",
    "Source": "pdf",
    "DEFAULT_CLASSIFICATION": "word",
    "WordConverter": "word",
    "DefaultConfig": "word",
}

__all__ = [
    "PdfConverter",
    "PDF_FONT_FAMILY",
    "SpanList",
    "Source",
    "DEFAULT_CLASSIFICATION",
    "WordConverter",
    "DefaultConfig",
]


def __getattr__(name: str) -> Any:
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f".{module}", __name__), name)
    globals()[name] = value  # resolve once; subsequent lookups skip __getattr__
    return value


def __dir__() -> list[str]:
    return sorted(__all__)
