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
from importlib import import_module
from wattleflow.core import IParser
from wattleflow.enums.filetype import FileType
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = ["ParserFactory"]

# --------------------------------------------------------------------------- #
# region ParserFactory                                                        #
# --------------------------------------------------------------------------- #


class ParserFactory:
    """Resolve an :class:`IParser` instance for a given :class:`FileType`."""

    # "submodule:ClassName" until first use, the resolved class afterwards.
    # Importing the parsers here would defeat the deferral the package declares:
    # `binary` reaches `helpers.image_security`, which requires Pillow, so an
    # eager registry pulls that tier on a bare install (DR-WFL-007).
    _REGISTRY: dict[FileType, str | type[IParser]] = {
        FileType.AVRO: "tabular:AvroParser",
        FileType.CSV: "tabular:CsvParser",
        FileType.DATAFRAME: "tabular:CsvParser",
        FileType.DOC: "word:DocParser",
        FileType.DOCX: "word:DocxParser",
        FileType.GRAPH: "text:GraphParser",
        FileType.JSON: "text:JsonParser",
        FileType.LOG: "text:LogParser",
        FileType.MARKDOWN: "text:MarkdownParser",
        FileType.ORC: "tabular:OrcParser",
        FileType.PDF: "binary:PdfParser",
        FileType.PICKLE: "binary:PickleParser",
        FileType.PNG: "binary:PngParser",
        FileType.PROTOBUF: "binary:ProtobufParser",
        FileType.RSS: "text:RssParser",
        FileType.TXT: "text:TxtParser",
        FileType.UNKNOWN: "text:TxtParser",
        FileType.XLS: "tabular:ExcelParser",
        FileType.XML: "text:XmlParser",
    }

    @classmethod
    def _resolve(cls, file_type: FileType) -> type[IParser]:
        """Import the parser for ``file_type`` on first use and memoise it."""
        try:
            entry = cls._REGISTRY[file_type]
        except KeyError as e:
            raise ValueError(f"No parser registered for FileType {file_type!r}") from e
        if isinstance(entry, str):
            module, _, name = entry.partition(":")
            entry = getattr(import_module(f".{module}", __package__), name)
            cls._REGISTRY[file_type] = entry
        return entry

    @classmethod
    def create(cls, file_type: FileType) -> IParser:
        """Return a parser instance for ``file_type``."""
        return cls._resolve(file_type)()

    @classmethod
    def register(cls, file_type: FileType, parser_cls: type[IParser]) -> None:
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
