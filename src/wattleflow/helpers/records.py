# Module name: helpers/records.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from typing import Any
from wattleflow.concrete import Document
from wattleflow.enums.filetype import FileType
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = ["DocumentRecords"]

# --------------------------------------------------------------------------- #
# region DocumentRecords                                                      #
# --------------------------------------------------------------------------- #


class DocumentRecords:
    """Records a pipeline hands to a write strategy, and the format to render them in.

    A slot keeps a second set of records apart from the data, such as a quality report.
    """

    CONTENT = "record_content"
    FORMAT = "record_format"
    QUALITY = "quality"
    DEFAULT = FileType.JSON

    @classmethod
    def file_type(cls, name: str | None) -> FileType:
        """FileType named by configuration, case-insensitively; the default when unset."""
        if not name:
            return cls.DEFAULT
        try:
            return FileType[str(name).upper()]
        except KeyError as e:
            raise ValueError(f"unknown record format {name!r}") from e

    @classmethod
    def stamp(cls, document: Document, content: Any, file_type: FileType, slot: str = "") -> None:
        """Put the content and its target format on the document, in the named slot."""
        document.update_metadata(cls.key(cls.CONTENT, slot), content)
        document.update_metadata(cls.key(cls.FORMAT, slot), file_type.name)

    @classmethod
    def content(cls, document: Document, slot: str = "") -> tuple[Any, FileType]:
        """Content and target format stamped in the named slot."""
        metadata = document.metadata
        return (
            metadata.get(cls.key(cls.CONTENT, slot)),
            cls.file_type(metadata.get(cls.key(cls.FORMAT, slot))),
        )

    @classmethod
    def records(cls, document: Document, slot: str = "") -> list[dict[str, Any]]:
        """The stamped content as a list of records; a feed yields its items."""
        content, _ = cls.content(document, slot)
        if isinstance(content, list):
            return content
        items = getattr(content, "items", None)
        return items if isinstance(items, list) else []

    @staticmethod
    def key(name: str, slot: str) -> str:
        """Metadata key of a slot."""
        return f"{name}_{slot}" if slot else name


# --------------------------------------------------------------------------- #
# endregion DocumentRecords                                                   #
# --------------------------------------------------------------------------- #
