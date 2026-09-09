# Module name: strategies/__init__.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# Lazy public API (PEP 562) — DR-WFL-007.
#
# Eager `from .<module> import ...` re-exports defeat the lazy-loading policy of
# §7.4: a single third-party-bound leaf makes the WHOLE package unimportable, so
# a name that needs nothing still requires the full dependency set.
# Measured: `from . import cryptography` pulled the `security` extra on any
# `import wattleflow.strategies`, which also nullified the already-deferred
# `strategies.documents` beneath it.
#
# Resolving a name imports ONLY the submodule that defines it. The public surface
# is unchanged and still explicit (NFRQ-SEC-02 t.2): `__all__` is complete and
# `_EXPORTS` states where each name lives.
#
# NOTE — `import *` resolves EVERY name in `__all__` and therefore still requires
# the full dependency set. That is the honest contract: asking for everything
# asks for everything. Named imports are the entry point on a partial install.
# --------------------------------------------------------------------------- #

from __future__ import annotations

from importlib import import_module
from typing import Any

# Public name -> defining subpackage. Extend this when a member is added; it is
# the single declaration of what this package exposes and from where.
_EXPORTS: dict[str, str] = {
    "StrategyBaseRSA": "cryptography",
    "StrategyRSAEncrypt256": "cryptography",
    "StrategyRSADecrypt256": "cryptography",
    "StrategyRSAEncrypt512": "cryptography",
    "StrategyRSADecrypt512": "cryptography",
    "StrategyFernetGeneric": "cryptography",
    "StrategyFernetEncrypt": "cryptography",
    "StrategyFernetDecrypt": "cryptography",
    "StrategyMD5": "cryptography",
    "StrategySha224": "cryptography",
    "StrategySha256": "cryptography",
    "StrategySha384": "cryptography",
    "StrategySha512": "cryptography",
    "StrategyFilename": "helpers",
    "StrategyFilterFiles": "helpers",
    "StrategyCopyHuggingfaceModels": "helpers",
    "StrategyClassLoader": "helpers",
}

__all__ = [
    "StrategyBaseRSA",
    "StrategyRSAEncrypt256",
    "StrategyRSADecrypt256",
    "StrategyRSAEncrypt512",
    "StrategyRSADecrypt512",
    "StrategyFernetGeneric",
    "StrategyFernetEncrypt",
    "StrategyFernetDecrypt",
    "StrategyMD5",
    "StrategySha224",
    "StrategySha256",
    "StrategySha384",
    "StrategySha512",
    "StrategyFilename",
    "StrategyFilterFiles",
    "StrategyCopyHuggingfaceModels",
    "StrategyClassLoader",
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
