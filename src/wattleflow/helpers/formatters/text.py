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
import json
from typing import Any, Union
from wattleflow.concrete.serialisation import GenericFormatter
from wattleflow.helpers.resource_config import ResourceConfig
from wattleflow.helpers.converters.rss import RssConverter, RssFeed
from wattleflow.helpers.converters.xml import XmlConverter
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = [
    "TextFormatter",
    "LogFormatter",
    "MarkdownFormatter",
    "JsonFormatter",
    "GraphFormatter",
    "RssFormatter",
    "XmlFormatter",
]

# --------------------------------------------------------------------------- #
# region Formatters                                                           #
# --------------------------------------------------------------------------- #


class TextFormatter(GenericFormatter):
    """Plain text — coerces non-str content via ``str``."""

    SUFFIX = ".txt"
    TEMPLATE = "text"

    def serialise(self, content: Any, **opts: Any) -> str:
        return content if isinstance(content, str) else str(content)


class LogFormatter(GenericFormatter):
    """Log text — coerces non-str content via ``str``."""

    SUFFIX = ".log"
    TEMPLATE = "log"

    def serialise(self, content: Any, **opts: Any) -> str:
        return content if isinstance(content, str) else str(content)


class MarkdownFormatter(GenericFormatter):
    """Markdown — accepts a python-docx Document, bytes or str."""

    SUFFIX = ".md"
    TEMPLATE = "markdown"

    def serialise(self, content: Any, **opts: Any) -> str:
        try:
            from docx.document import Document as DocumentT
        except ImportError:
            DocumentT = None

        from wattleflow.helpers.converters import WordConverter

        if DocumentT is not None and isinstance(content, DocumentT):
            return WordConverter.docx_to_markdown(content)
        if isinstance(content, (bytes, bytearray)):
            return bytes(content).decode(ResourceConfig.formatter(self.TEMPLATE, opts)["encoding"])
        if isinstance(content, str):
            return content
        raise TypeError(
            f"MarkdownFormatter: unsupported content type {type(content).__name__}"
        )


class JsonFormatter(GenericFormatter):
    """JSON (RFC 8259) — passes str/bytes through; serialises records or a pandas DataFrame."""

    SUFFIX = ".json"
    TEMPLATE = "json"

    def serialise(self, content: Any, **opts: Any) -> Union[str, bytes]:
        if isinstance(content, str):
            return content
        if isinstance(content, (bytes, bytearray)):
            return bytes(content)
        if not isinstance(content, (list, dict)):
            import pandas as pd

            if not isinstance(content, pd.DataFrame):
                raise TypeError(
                    "JSON write expects str/bytes, records (list/dict) or pd.DataFrame; "
                    f"got {type(content).__name__}"
                )
            # v0.0.4 (DR-PRC-008): a DataFrame is written as its records, so one engine reads the template.
            content = content.astype(object).where(content.notna(), None).to_dict(orient="records")
        settings = ResourceConfig.formatter(self.TEMPLATE, opts)
        return json.dumps(
            content, ensure_ascii=settings["ensure_ascii"], default=str, indent=settings["indent"]
        )


class GraphFormatter(GenericFormatter):
    """RDF graph — serialises an rdflib Graph to JSON-LD by default."""

    SUFFIX = ".json"
    TEMPLATE = "graph"

    def serialise(self, content: Any, **opts: Any) -> str:
        from rdflib import Graph

        if not isinstance(content, Graph):
            raise TypeError(
                f"GraphFormatter: expected rdflib Graph, got {type(content).__name__}"
            )
        settings = ResourceConfig.formatter(self.TEMPLATE, opts)
        return content.serialize(format=settings["format"], indent=settings["indent"])


class RssFormatter(GenericFormatter):
    """RSS 2.0 — renders an RssFeed, or a list of item records under the `channel` option."""

    SUFFIX = ".rss"
    TEMPLATE = "rss"

    def serialise(self, content: Any, **opts: Any) -> str:
        if isinstance(content, list):
            content = RssFeed(channel=ResourceConfig.formatter(self.TEMPLATE, opts)["channel"], items=content)
        if not isinstance(content, RssFeed):
            raise TypeError(f"RssFormatter: unsupported content type {type(content).__name__}")
        return RssConverter.to_rss(content)


class XmlFormatter(GenericFormatter):
    """XML — renders a list of flat records under the `root` and `record` element names."""

    SUFFIX = ".xml"
    TEMPLATE = "xml"

    def serialise(self, content: Any, **opts: Any) -> str:
        if not isinstance(content, list):
            raise TypeError(f"XmlFormatter: unsupported content type {type(content).__name__}")
        settings = ResourceConfig.formatter(self.TEMPLATE, opts)
        return XmlConverter.from_records(content, root=settings["root"], record=settings["record"])


# --------------------------------------------------------------------------- #
# endregion Formatters                                                        #
# --------------------------------------------------------------------------- #
