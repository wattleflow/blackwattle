# Module name: strategies/documents/xml.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from wattleflow.enums.filetype import FileType
from .records import ReadDocumentRecords
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = ["ReadXmlDocument"]

# --------------------------------------------------------------------------- #
# region Strategies                                                           #
# --------------------------------------------------------------------------- #


class ReadXmlDocument(ReadDocumentRecords):
    """Read a stored XML document; each child of the root becomes a record."""

    CONTENT = list
    FILE_TYPE = FileType.XML


# --------------------------------------------------------------------------- #
# endregion Strategies                                                        #
# --------------------------------------------------------------------------- #
