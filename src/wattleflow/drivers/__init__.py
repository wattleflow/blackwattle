# Module name: drivers/__init__.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# Lazy public API (PEP 562).
#
# Eager `from .<module> import ...` re-exports defeated the lazy-loading policy
# of §7.4: every third-party driver raises ModuleNotFoundError at IMPORT time,
# so `from wattleflow.drivers import DriverLocalStorage` — a driver with no
# third-party dependency at all — required elasticsearch, kafka, pyspark,
# psycopg2, pysolr, boto3 and pyarrow to be installed. A slim runtime image
# that installs none of them could not import the package.
#
# Resolving a name imports ONLY the submodule that defines it. The public
# surface is unchanged and still explicit (NFRQ-SEC-02 t.2): `__all__` is
# complete and `_EXPORTS` states where each name lives.
#
# NOTE — `from wattleflow.drivers import *` resolves EVERY name in `__all__`
# and therefore still requires the full dependency set. That is the honest
# contract: asking for everything asks for everything. Named imports are the
# supported entry point on a partial installation.
# --------------------------------------------------------------------------- #

from __future__ import annotations

from importlib import import_module
from typing import Any

# Public name -> defining submodule. Extend this when a driver is added; it is
# the single declaration of what this package exposes and from where.
_EXPORTS: dict[str, str] = {
    "DriverAvro": "avro",
    "DriverAvroError": "avro",
    "DriverClaude": "claude",
    "DriverLanguageModel": "language_model",
    "DriverLanguageModelError": "language_model",
    "DriverClaudeException": "claude",
    "DriverElasticSearch": "elasticsearch",
    "DriverElasticSearchError": "elasticsearch",
    "DriverFactory": "factory",
    "FileStorage": "file_storage",
    "DriverGrafana": "grafana",
    "DriverGrafanaError": "grafana",
    "DriverHttpProxy": "http_proxy",
    "DriverKafka": "kafka",
    "DriverKafkaError": "kafka",
    "DriverKibana": "kibana",
    "DriverKibanaError": "kibana",
    "DriverLocalStorage": "local_storage",
    "DriverLocalStorageException": "local_storage",
    "DriverOpenSearch": "opensearch",
    "DriverOpenSearchError": "opensearch",
    "DriverOrc": "orc",
    "DriverPdf": "pdf",
    "DriverPdfError": "pdf",
    "PdfRead": "pdf",
    "DriverOrcError": "orc",
    "DriverProxy": "proxy",
    "DriverProxyError": "proxy",
    "DriverPostgres": "postgres",
    "DriverPostgresError": "postgres",
    "DriverPrometheus": "prometheus",
    "DriverPrometheusError": "prometheus",
    "DriverProtobuf": "protobuf",
    "DriverProtobufError": "protobuf",
    "DriverS3": "s3bucket",
    "DriverSDR": "sdr",
    "DriverSDRError": "sdr",
    "SDRDeviceLost": "sdr",
    "SDRSampleBlock": "sdr",
    "SDRTransmitNotSupported": "sdr",
    "DriverSolr": "solr",
    "DriverSolrError": "solr",
    "DriverSpark": "spark",
    "DriverSparkError": "spark",
    "DriverSqlite": "sqlite",
    "DriverSqliteError": "sqlite",
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
