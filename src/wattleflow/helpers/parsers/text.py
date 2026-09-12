# Module name: helpers/parsers/text.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


"""
Text-family parsers — deserialise plain-text, log, Markdown, JSON and RDF
graph streams into domain objects. Parsers only deserialise (no path-security,
no I/O policy, no logging).
"""

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from typing import Any, BinaryIO
from wattleflow.concrete.serialisation import GenericParser
from wattleflow.helpers.converters.rss import RssConverter, RssFeed
from wattleflow.helpers.converters.xml import XmlConverter
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = [
    "TxtParser",
    "LogParser",
    "MarkdownParser",
    "JsonParser",
    "GraphParser",
    "RssParser",
    "XmlParser",
]

# --------------------------------------------------------------------------- #
# region Parsers                                                              #
# --------------------------------------------------------------------------- #


class TxtParser(GenericParser):
    def deserialise(self, reader: BinaryIO, **opts: Any) -> str:
        return self.decode(reader, **opts)


class LogParser(GenericParser):
    def deserialise(self, reader: BinaryIO, **opts: Any) -> str:
        return self.decode(reader, **opts)


class MarkdownParser(GenericParser):
    def deserialise(self, reader: BinaryIO, **opts: Any) -> str:
        return self.decode(reader, **opts)


class JsonParser(GenericParser):
    """Return the raw JSON text. Parsing is a strategy concern."""

    def deserialise(self, reader: BinaryIO, **opts: Any) -> str:
        return self.decode(reader, **opts)


class GraphParser(GenericParser):
    def deserialise(self, reader: BinaryIO, **opts: Any) -> Any:
        from rdflib import Graph

        fmt = opts.pop("format", None)
        graph = Graph()
        graph.parse(source=reader, format=fmt) if fmt else graph.parse(source=reader)
        return graph



class RssParser(GenericParser):
    """Read an RSS document into an RssFeed; the XML declaration decides the encoding."""

    def deserialise(self, reader: BinaryIO, **opts: Any) -> RssFeed:
        return RssConverter.to_feed(reader.read())


class XmlParser(GenericParser):
    """Read an XML document into flat records; the `record` option names the repeating element."""

    def deserialise(self, reader: BinaryIO, **opts: Any) -> list[dict[str, Any]]:
        return XmlConverter.to_records(reader.read(), opts.get("record"))


# --------------------------------------------------------------------------- #
# endregion Parsers                                                           #
# --------------------------------------------------------------------------- #
