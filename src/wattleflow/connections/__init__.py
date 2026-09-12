# Module name: connections/__init__.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# Lazy public API (PEP 562) — same rationale as drivers/__init__.py.
#
# Every connection here wraps a third-party client that raises at import time
# when its library is absent, so eager re-exports made the package unimportable
# on a runtime image that installs only the libraries it actually uses.
# Resolving a name imports ONLY the submodule that defines it (§7.4).
#
# NOTE — `from wattleflow.connections import *` resolves EVERY name in
# `__all__` and still requires the full dependency set.
# --------------------------------------------------------------------------- #

from __future__ import annotations

from importlib import import_module
from typing import Any

# Public name -> defining submodule. Extend this when a connection is added.
_EXPORTS: dict[str, str] = {
    "AISStreamConnection": "aisstream",
    "AISStreamError": "aisstream",
    "ElasticSearchConnection": "elasticsearch",
    "ElasticSearchConnectionError": "elasticsearch",
    "ConnectionHuggingFace": "huggingface",
    "HuggingFaceConnectionError": "huggingface",
    "GFWConnection": "gfw",
    "GFWConnectionError": "gfw",
    "OpenSearchConnection": "opensearch",
    "OpenSearchConnectionError": "opensearch",
    "ProxyConnection": "proxy",
    "ProxyConnectionError": "proxy",
    "KafkaConnectionError": "kafka",
    "KafkaConsumerConnection": "kafka",
    "KafkaProducerConnection": "kafka",
    "PostgresConnection": "postgres",
    "PostgresError": "postgres",
    "SFTPConnection": "sftp_paramiko",
    "SFTPConnectionError": "sftp_paramiko",
    "SDRConnection": "sdr",
    "SDRConnectionError": "sdr",
    "SolrConnection": "solr",
    "SqliteConnection": "sqlite",
    "SqliteConnectionError": "sqlite",
    "SolrConnectionError": "solr",
    "SparkConnection": "spark",
    "SparkConnectionError": "spark",
    "TikaClient": "tika",
    "TikaConnection": "tika",
    "TikaConnectionError": "tika",
    "TikaJavaError": "tika",
    "TikaLocalConnection": "tika",
    "TikaRuntime": "tika",
    "TikaServerConnection": "tika",
    "TikaServerJarError": "tika",
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
