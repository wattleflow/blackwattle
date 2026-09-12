# Module name: helpers/formatters/factory.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


"""
FormatterFactory — map a FileType to the Formatter that serialises it.

Write strategies resolve a Formatter here, call ``render``/``stream`` to produce
the payload, then hand it to ``DriverLocalStorage.persist``/``open_target``.
Custom formats register via ``FormatterFactory.register(file_type, cls)``.
"""

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from typing import Dict, Type
from wattleflow.core import IFormatter
from wattleflow.enums.filetype import FileType
from .binary import PdfFormatter, PickleFormatter, PngFormatter, ProtobufFormatter
from .tabular import AvroFormatter, CsvFormatter, ExcelFormatter, OrcFormatter
from .text import (
    GraphFormatter,
    JsonFormatter,
    LogFormatter,
    MarkdownFormatter,
    RssFormatter,
    TextFormatter,
    XmlFormatter,
)
from .word import DocFormatter, WordFormatter
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = ["FormatterFactory"]

# --------------------------------------------------------------------------- #
# region FormatterFactory                                                     #
# --------------------------------------------------------------------------- #


class FormatterFactory:
    """Resolve a :class:`IFormatter` instance for a given :class:`FileType`."""

    _REGISTRY: Dict[FileType, Type[IFormatter]] = {
        FileType.TXT: TextFormatter,
        FileType.UNKNOWN: TextFormatter,
        FileType.LOG: LogFormatter,
        FileType.MARKDOWN: MarkdownFormatter,
        FileType.JSON: JsonFormatter,
        FileType.GRAPH: GraphFormatter,
        FileType.RSS: RssFormatter,
        FileType.XML: XmlFormatter,
        FileType.CSV: CsvFormatter,
        FileType.DATAFRAME: CsvFormatter,
        FileType.XLS: ExcelFormatter,
        FileType.ORC: OrcFormatter,
        FileType.AVRO: AvroFormatter,
        FileType.PDF: PdfFormatter,
        FileType.PICKLE: PickleFormatter,
        FileType.PROTOBUF: ProtobufFormatter,
        FileType.PNG: PngFormatter,
        FileType.DOCX: WordFormatter,
        FileType.DOC: DocFormatter,
    }

    @classmethod
    def create(cls, file_type: FileType) -> IFormatter:
        """Return a Formatter instance for ``file_type``."""
        try:
            formatter_cls = cls._REGISTRY[file_type]
        except KeyError as e:
            raise ValueError(f"No formatter registered for FileType {file_type!r}") from e
        return formatter_cls()

    @classmethod
    def register(cls, file_type: FileType, formatter_cls: Type[IFormatter]) -> None:
        """Register (or override) the Formatter for ``file_type``."""
        if not issubclass(formatter_cls, IFormatter):
            raise TypeError("formatter_cls must implement IFormatter")
        cls._REGISTRY[file_type] = formatter_cls

    @classmethod
    def supports(cls, file_type: FileType) -> bool:
        return file_type in cls._REGISTRY


# --------------------------------------------------------------------------- #
# endregion FormatterFactory                                                  #
# --------------------------------------------------------------------------- #
