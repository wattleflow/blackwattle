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
from importlib import import_module
from wattleflow.core import IFormatter
from wattleflow.enums.filetype import FileType
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = ["FormatterFactory"]

# --------------------------------------------------------------------------- #
# region FormatterFactory                                                     #
# --------------------------------------------------------------------------- #


class FormatterFactory:
    """Resolve a :class:`IFormatter` instance for a given :class:`FileType`."""

    # "submodule:ClassName" until first use, the resolved class afterwards.
    # Importing the formatters here would defeat the deferral the package
    # declares: `binary` reaches `helpers.image_security`, which requires Pillow,
    # so an eager registry pulls that tier on a bare install (DR-WFL-007).
    _REGISTRY: dict[FileType, str | type[IFormatter]] = {
        FileType.TXT: "text:TextFormatter",
        FileType.UNKNOWN: "text:TextFormatter",
        FileType.LOG: "text:LogFormatter",
        FileType.MARKDOWN: "text:MarkdownFormatter",
        FileType.JSON: "text:JsonFormatter",
        FileType.GRAPH: "text:GraphFormatter",
        FileType.RSS: "text:RssFormatter",
        FileType.XML: "text:XmlFormatter",
        FileType.CSV: "tabular:CsvFormatter",
        FileType.DATAFRAME: "tabular:CsvFormatter",
        FileType.XLS: "tabular:ExcelFormatter",
        FileType.ORC: "tabular:OrcFormatter",
        FileType.AVRO: "tabular:AvroFormatter",
        FileType.PDF: "binary:PdfFormatter",
        FileType.PICKLE: "binary:PickleFormatter",
        FileType.PROTOBUF: "binary:ProtobufFormatter",
        FileType.PNG: "binary:PngFormatter",
        FileType.DOCX: "word:WordFormatter",
        FileType.DOC: "word:DocFormatter",
    }

    @classmethod
    def _resolve(cls, file_type: FileType) -> type[IFormatter]:
        """Import the Formatter for ``file_type`` on first use and memoise it."""
        try:
            entry = cls._REGISTRY[file_type]
        except KeyError as e:
            raise ValueError(f"No formatter registered for FileType {file_type!r}") from e
        if isinstance(entry, str):
            module, _, name = entry.partition(":")
            entry = getattr(import_module(f".{module}", __package__), name)
            cls._REGISTRY[file_type] = entry
        return entry

    @classmethod
    def create(cls, file_type: FileType) -> IFormatter:
        """Return a Formatter instance for ``file_type``."""
        return cls._resolve(file_type)()

    @classmethod
    def register(cls, file_type: FileType, formatter_cls: type[IFormatter]) -> None:
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
