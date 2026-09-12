# Module name: helpers/parsers/factory.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


"""
ParserFactory — map a FileType to the Parser that deserialises it.

``DriverLocalStorage.read`` validates/detects and opens the file, then resolves
a parser here and calls ``parse(stream=..., **opts)``. The read-side mirror of
FormatterFactory.
Custom formats register via ``ParserFactory.register(file_type, cls)``.
"""

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from typing import Dict, Type
from wattleflow.core import IParser
from wattleflow.enums.filetype import FileType
from .binary import PdfParser, PickleParser, PngParser, ProtobufParser
from .tabular import AvroParser, CsvParser, ExcelParser, OrcParser
from .text import (
    GraphParser,
    JsonParser,
    LogParser,
    MarkdownParser,
    RssParser,
    TxtParser,
    XmlParser,
)
from .word import DocParser, DocxParser
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = ["ParserFactory"]

# --------------------------------------------------------------------------- #
# region ParserFactory                                                        #
# --------------------------------------------------------------------------- #


class ParserFactory:
    """Resolve an :class:`IParser` instance for a given :class:`FileType`."""

    _REGISTRY: Dict[FileType, Type[IParser]] = {
        FileType.AVRO: AvroParser,
        FileType.CSV: CsvParser,
        FileType.DATAFRAME: CsvParser,
        FileType.DOC: DocParser,
        FileType.DOCX: DocxParser,
        FileType.GRAPH: GraphParser,
        FileType.JSON: JsonParser,
        FileType.LOG: LogParser,
        FileType.MARKDOWN: MarkdownParser,
        FileType.ORC: OrcParser,
        FileType.PDF: PdfParser,
        FileType.PICKLE: PickleParser,
        FileType.PNG: PngParser,
        FileType.PROTOBUF: ProtobufParser,
        FileType.RSS: RssParser,
        FileType.TXT: TxtParser,
        FileType.UNKNOWN: TxtParser,
        FileType.XLS: ExcelParser,
        FileType.XML: XmlParser,
    }

    @classmethod
    def create(cls, file_type: FileType) -> IParser:
        """Return a parser instance for ``file_type``."""
        try:
            parser_cls = cls._REGISTRY[file_type]
        except KeyError as e:
            raise ValueError(f"No parser registered for FileType {file_type!r}") from e
        return parser_cls()

    @classmethod
    def register(cls, file_type: FileType, parser_cls: Type[IParser]) -> None:
        """Register (or override) the parser for ``file_type``."""
        if not issubclass(parser_cls, IParser):
            raise TypeError("parser_cls must implement IParser")
        cls._REGISTRY[file_type] = parser_cls

    @classmethod
    def supports(cls, file_type: FileType) -> bool:
        return file_type in cls._REGISTRY


# --------------------------------------------------------------------------- #
# endregion ParserFactory                                                     #
# --------------------------------------------------------------------------- #
