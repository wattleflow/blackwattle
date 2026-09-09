# Module name: helpers/cloud/__init__.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# Lazy public API (PEP 562) — DR-WFL-007.
#
# The package carries an __init__.py so that it is a package of THIS
# distribution and not an implicit PEP 420 namespace. A namespace merges with any
# same-named directory another distribution ships, and `import *` over one yields
# nothing without raising (CLAUDE.md 2.6, 2.7 t.1, DR-WFL-017).
# Resolution stays deferred although no submodule needs a third-party library at
# import today: the form matches the sibling packages, and it keeps that true if
# a resolver later imports a cloud SDK at module level (DR-WFL-007).
# --------------------------------------------------------------------------- #

from __future__ import annotations

from importlib import import_module
from typing import Any

# Public name -> defining submodule. Extend this when a member is added; it is
# the single declaration of what this package exposes and from where.
_EXPORTS: dict[str, str] = {
    "AwsSecretsResolver": "cloud_secrets",
    "AzureKeyVaultResolver": "cloud_secrets",
    "GcpSecretResolver": "cloud_secrets",
    "VaultResolver": "cloud_secrets",
}

__all__ = [
    "AwsSecretsResolver",
    "AzureKeyVaultResolver",
    "GcpSecretResolver",
    "VaultResolver",
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
