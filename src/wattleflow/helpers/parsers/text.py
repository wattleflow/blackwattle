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
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = [
    "TxtParser",
    "LogParser",
    "MarkdownParser",
    "JsonParser",
    "GraphParser",
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


# --------------------------------------------------------------------------- #
# endregion Parsers                                                           #
# --------------------------------------------------------------------------- #
