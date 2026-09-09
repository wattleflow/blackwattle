# Module name: helpers/formatters/text.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


"""
Text-family Formatters — serialise content into text payloads.

Each Formatter turns ``content`` into a ``str`` / ``bytes`` payload; the driver
persists it. Serialisation logic ported from ``DriverLocalStorage._write_*``;
all path/storage/debug concerns stay in the driver.
"""

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from typing import Any, Union
from wattleflow.concrete.serialisation import GenericFormatter
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = [
    "TextFormatter",
    "LogFormatter",
    "MarkdownFormatter",
    "JsonFormatter",
    "GraphFormatter",
]

# --------------------------------------------------------------------------- #
# region Formatters                                                           #
# --------------------------------------------------------------------------- #


class TextFormatter(GenericFormatter):
    """Plain text — coerces non-str content via ``str``."""

    SUFFIX = ".txt"

    def serialise(self, content: Any, **opts: Any) -> str:
        return content if isinstance(content, str) else str(content)


class LogFormatter(GenericFormatter):
    """Log text — coerces non-str content via ``str``."""

    SUFFIX = ".log"

    def serialise(self, content: Any, **opts: Any) -> str:
        return content if isinstance(content, str) else str(content)


class MarkdownFormatter(GenericFormatter):
    """Markdown — accepts a python-docx Document, bytes or str."""

    SUFFIX = ".md"

    def serialise(self, content: Any, **opts: Any) -> str:
        try:
            from docx.document import Document as DocumentT
        except ImportError:
            DocumentT = None

        from wattleflow.helpers.converters import WordConverter

        if DocumentT is not None and isinstance(content, DocumentT):
            return WordConverter.docx_to_markdown(content)
        if isinstance(content, (bytes, bytearray)):
            return bytes(content).decode("utf-8")
        if isinstance(content, str):
            return content
        raise TypeError(
            f"MarkdownFormatter: unsupported content type {type(content).__name__}"
        )


class JsonFormatter(GenericFormatter):
    """JSON — passes str/bytes through; serialises a pandas DataFrame."""

    SUFFIX = ".json"

    def serialise(self, content: Any, **opts: Any) -> Union[str, bytes]:
        import pandas as pd

        if isinstance(content, str):
            return content
        if isinstance(content, (bytes, bytearray)):
            return bytes(content)
        if isinstance(content, pd.DataFrame):
            return content.to_json(**opts)
        raise TypeError(
            "JSON write expects str/bytes (or pd.DataFrame); "
            f"got {type(content).__name__}"
        )


class GraphFormatter(GenericFormatter):
    """RDF graph — serialises an rdflib Graph to JSON-LD by default."""

    SUFFIX = ".json"

    def serialise(self, content: Any, **opts: Any) -> str:
        from rdflib import Graph

        if not isinstance(content, Graph):
            raise TypeError(
                f"GraphFormatter: expected rdflib Graph, got {type(content).__name__}"
            )
        return content.serialize(
            format=opts.get("format", "json-ld"),
            indent=opts.get("indent", 2),
        )


# --------------------------------------------------------------------------- #
# endregion Formatters                                                        #
# --------------------------------------------------------------------------- #
