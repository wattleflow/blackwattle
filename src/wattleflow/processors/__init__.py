# Module name: processors/__init__.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# Lazy public API (PEP 562) — same rationale as drivers/__init__.py.
#
# Eager re-exports made `from wattleflow.processors import OCRTextProcessor`
# require opensearch-py, kafka-python, pyspark, psycopg2, pysolr and pyarrow,
# because each of those processor modules imports its driver at module level
# and the driver raises at import time. Resolving a name now imports ONLY the
# submodule that defines it (§7.4 lazy-loading).
#
# NOTE — `from wattleflow.processors import *` resolves EVERY name in
# `__all__` and still requires the full dependency set.
# --------------------------------------------------------------------------- #

from __future__ import annotations

from importlib import import_module
from typing import Any

# Public name -> defining submodule. Extend this when a processor is added.
_EXPORTS: dict[str, str] = {
    "AvroReadProcessor": "avro",
    "AvroWriteProcessor": "avro",
    "FileDocumentProcessor": "file",
    "KafkaReadProcessor": "kafka",
    "KafkaWriteProcessor": "kafka",
    "OpenSearchReadProcessor": "opensearch",
    "OpenSearchWriteProcessor": "opensearch",
    "OrcReadProcessor": "orc",
    "OrcWriteProcessor": "orc",
    "PostgresReadProcessor": "postgres",
    "SolrReadProcessor": "solr",
    "SolrWriteProcessor": "solr",
    "SparkReadProcessor": "spark",
    "SparkWriteProcessor": "spark",
    "TesseractProcessor": "tesseract",
    "OCRTextProcessor": "ocr",
    "YoutubeError": "youtube",
    "YoutubeProcessor": "youtube",
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
